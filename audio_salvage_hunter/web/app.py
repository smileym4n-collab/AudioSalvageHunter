from __future__ import annotations

import csv
import os
from io import StringIO
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .database import SessionLocal, get_db, init_db
from .importers import import_donors_csv_text, import_legacy_seen_sqlite, seed_donors_from_csv, seed_search_terms_from_config
from .logging_config import LOG_FILE, configure_logging, read_recent_logs
from .models import DonorRecord, ListingRecord, PriceHistoryRecord, ScanRunRecord, SearchTermRecord
from .scheduler import configure_scheduler, next_run_time, pause_scheduler, resume_scheduler, scheduler_status, shutdown_scheduler
from .schemas import DonorIn, DonorOut, ScanOut, ScanRequest, SearchTermIn, SearchTermOut, SettingsIn
from .security import auth_enabled, csrf_token, login_redirect, require_login, safe_next_path, secret_status, validate_csrf, verify_password
from .services import create_scan, donor_records_as_csv_file, listing_query, mark_stale_running_scans, remove_mock_data, scan_status, start_scan_background, wait_for_scan_shutdown
from .settings import format_local_datetime, get_settings, seed_settings_from_config, update_settings


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def create_app() -> FastAPI:
    app = FastAPI(title="Audio Salvage Hunter", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    secret_key = os.getenv("APP_SECRET_KEY", "dev-only-change-me")
    app.add_middleware(SessionMiddleware, secret_key=secret_key, https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true", same_site="lax")

    @app.middleware("http")
    async def protect_docs_when_auth_enabled(request: Request, call_next):
        session = request.scope.get("session", {})
        if request.url.path in {"/docs", "/redoc", "/openapi.json"} and auth_enabled() and session.get("authenticated") is not True:
            return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
        return await call_next(request)

    @app.on_event("startup")
    def startup() -> None:
        init_db()
        with SessionLocal() as db:
            mark_stale_running_scans(db)
            seed_settings_from_config(db)
            configure_logging(get_settings(db)["log_level"])
            seed_donors_from_csv(db)
            seed_search_terms_from_config(db)
            import_legacy_seen_sqlite(db, "audio_salvage_hunter.sqlite3")
        configure_scheduler(app)

    @app.on_event("shutdown")
    def shutdown() -> None:
        shutdown_scheduler()
        wait_for_scan_shutdown(timeout_seconds=float(os.getenv("SCAN_SHUTDOWN_WAIT_SECONDS", "10")))

    register_routes(app)
    return app


def context(request: Request, db: Session, **extra):
    values = {"request": request, "csrf_token": csrf_token(request), "auth_enabled": auth_enabled(), "settings": get_settings(db), "fmt_dt": lambda value: format_local_datetime(db, value)}
    values.update(extra)
    return values


def guard(request: Request):
    redirect = login_redirect(request)
    if redirect:
        return redirect
    return None


def parse_form_bool(value: str | None) -> bool:
    return value in {"1", "true", "on", "yes"}


def donor_from_form(form) -> DonorIn:
    return DonorIn(
        manufacturer=form.get("manufacturer", "").strip(),
        model=form.get("model", "").strip(),
        aliases=form.get("aliases", "").strip(),
        category=form.get("category", "").strip(),
        likely_valuable_components=form.get("likely_valuable_components", "").strip(),
        component_type=form.get("component_type", "").strip(),
        confidence_level=form.get("confidence_level", "uncertain"),
        desirability_score=int(form.get("desirability_score") or 0),
        maximum_worthwhile_delivered_price_gbp=float(form.get("maximum_worthwhile_delivered_price_gbp") or 0),
        ideal_fault_types=form.get("ideal_fault_types", "").strip(),
        risky_fault_types=form.get("risky_fault_types", "").strip(),
        salvage_difficulty=form.get("salvage_difficulty", "").strip(),
        package_or_removal_notes=form.get("package_or_removal_notes", "").strip(),
        source_or_verification_note=form.get("source_or_verification_note", "").strip(),
        general_comments=form.get("general_comments", "").strip(),
    )


def apply_donor(record: DonorRecord, data: DonorIn) -> DonorRecord:
    for key, value in data.model_dump().items():
        setattr(record, key, value)
    return record


def register_routes(app: FastAPI) -> None:
    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, db: Session = Depends(get_db), next: str = "/"):
        return templates.TemplateResponse(request, "login.html", context(request, db, next=safe_next_path(next), error=""))

    @app.post("/login")
    async def login(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        username = os.getenv("AUTH_USERNAME", "")
        password_hash = os.getenv("AUTH_PASSWORD_HASH", "")
        if form.get("username") == username and verify_password(str(form.get("password", "")), password_hash):
            request.session["authenticated"] = True
            csrf_token(request)
            return RedirectResponse(safe_next_path(form.get("next")), status_code=303)
        return templates.TemplateResponse(request, "login.html", context(request, db, next=safe_next_path(form.get("next")), error="Invalid login"), status_code=401)

    @app.post("/logout")
    async def logout(request: Request):
        form = await request.form()
        validate_csrf(request, dict(form))
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        settings = get_settings(db)
        total = db.query(ListingRecord).count()
        last_scan = db.query(ScanRunRecord).filter_by(status="success").order_by(ScanRunRecord.finished_at.desc()).first()
        latest_scan = db.query(ScanRunRecord).order_by(ScanRunRecord.id.desc()).first()
        new_since = latest_scan.new_listings if latest_scan else 0
        above = db.query(ListingRecord).filter(ListingRecord.score >= int(settings["minimum_alert_score"])).count()
        drops = db.query(ListingRecord).filter(ListingRecord.last_price_reduction.is_not(None)).count()
        listings = db.query(ListingRecord).order_by(ListingRecord.score.desc(), ListingRecord.total_price.asc()).limit(12).all()
        schedule = scheduler_status(settings.get("mock_mode") == "true")
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            context(
                request,
                db,
                total=total,
                new_since=new_since,
                above=above,
                drops=drops,
                last_scan=last_scan,
                next_scan=next_run_time(),
                schedule=schedule,
                api_status="configured" if os.getenv("EBAY_CLIENT_ID") and os.getenv("EBAY_CLIENT_SECRET") else "missing credentials",
                db_status="ok",
                telegram_status="configured" if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID") else "not configured",
                listings=listings,
                scan_status=scan_status(),
            ),
        )

    @app.get("/listings", response_class=HTMLResponse)
    def listings_page(request: Request, db: Session = Depends(get_db), page: int = 1, sort: str = "score"):
        if redirect := guard(request):
            return redirect
        params = dict(request.query_params)
        params["sort"] = sort
        per_page = 25
        query = listing_query(db, params)
        total = query.count()
        rows = query.offset(max(page - 1, 0) * per_page).limit(per_page).all()
        return templates.TemplateResponse(request, "listings.html", context(request, db, listings=rows, page=page, pages=max((total + per_page - 1) // per_page, 1), total=total, params=params))

    @app.get("/listings/{item_id}", response_class=HTMLResponse)
    def listing_detail(request: Request, item_id: str, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        listing = db.query(ListingRecord).filter_by(item_id=item_id).one_or_none()
        if not listing:
            raise HTTPException(404, "Listing not found")
        donor = None
        if listing.matched_donor:
            parts = listing.matched_donor.split(" ", 1)
            donor = db.query(DonorRecord).filter(DonorRecord.manufacturer == parts[0], DonorRecord.model == (parts[1] if len(parts) > 1 else listing.matched_donor)).first()
        history = db.query(PriceHistoryRecord).filter_by(listing_id=listing.id).order_by(PriceHistoryRecord.seen_at.desc()).all()
        return templates.TemplateResponse(request, "listing_detail.html", context(request, db, listing=listing, donor=donor, history=history))

    @app.get("/scan", response_class=HTMLResponse)
    def scan_page(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        groups = [row[0] for row in db.query(SearchTermRecord.group_name).distinct().all()]
        scans = db.query(ScanRunRecord).order_by(ScanRunRecord.id.desc()).limit(20).all()
        return templates.TemplateResponse(request, "scan.html", context(request, db, groups=groups, scans=scans, scan_status=scan_status()))

    @app.post("/scan")
    async def scan_start(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        if scan_status()["running"]:
            return RedirectResponse("/scan?error=running", status_code=303)
        scan = create_scan(db, mode=form.get("mode") or "live", query_group=form.get("query_group") or "", custom_query=form.get("custom_query") or "", notifications_enabled=parse_form_bool(form.get("notifications_enabled")))
        start_scan_background(app, scan.id)
        return RedirectResponse(f"/scan?scan_id={scan.id}", status_code=303)

    @app.get("/donors", response_class=HTMLResponse)
    def donors_page(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        q = request.query_params.get("q", "")
        query = db.query(DonorRecord)
        if q:
            like = f"%{q}%"
            query = query.filter((DonorRecord.manufacturer.ilike(like)) | (DonorRecord.model.ilike(like)) | (DonorRecord.likely_valuable_components.ilike(like)))
        for key, column in [("category", DonorRecord.category), ("confidence", DonorRecord.confidence_level)]:
            if request.query_params.get(key):
                query = query.filter(column == request.query_params[key])
        donors = query.order_by(DonorRecord.manufacturer, DonorRecord.model).limit(300).all()
        return templates.TemplateResponse(request, "donors.html", context(request, db, donors=donors, donor=None))

    @app.post("/donors")
    async def donors_save(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        data = donor_from_form(form)
        record = db.get(DonorRecord, int(form["id"])) if form.get("id") else DonorRecord(manufacturer=data.manufacturer, model=data.model)
        apply_donor(record, data)
        db.add(record)
        db.commit()
        return RedirectResponse("/donors", status_code=303)

    @app.post("/donors/{donor_id}/delete")
    async def donor_delete(request: Request, donor_id: int, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        donor = db.get(DonorRecord, donor_id)
        if donor:
            db.delete(donor)
            db.commit()
        return RedirectResponse("/donors", status_code=303)

    @app.get("/donors/export")
    def donors_export(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        return Response(donor_records_as_csv_file(db), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=donor_database_export.csv"})

    @app.post("/donors/import")
    async def donors_import(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        text = (await file.read()).decode("utf-8")
        import_donors_csv_text(db, text)
        return RedirectResponse("/donors", status_code=303)

    @app.get("/searches", response_class=HTMLResponse)
    def searches_page(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        terms = db.query(SearchTermRecord).order_by(SearchTermRecord.group_name, SearchTermRecord.term).all()
        return templates.TemplateResponse(request, "searches.html", context(request, db, terms=terms))

    @app.post("/searches")
    async def searches_save(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        data = SearchTermIn(term=form.get("term", ""), group_name=form.get("group_name", ""), enabled=parse_form_bool(form.get("enabled")), maximum_price=float(form["maximum_price"]) if form.get("maximum_price") else None, category=form.get("category", ""), notes=form.get("notes", ""))
        record = db.get(SearchTermRecord, int(form["id"])) if form.get("id") else SearchTermRecord()
        for key, value in data.model_dump().items():
            setattr(record, key, value)
        db.add(record)
        db.commit()
        return RedirectResponse("/searches", status_code=303)

    @app.post("/searches/{term_id}/delete")
    async def searches_delete(request: Request, term_id: int, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        term = db.get(SearchTermRecord, term_id)
        if term:
            db.delete(term)
            db.commit()
        return RedirectResponse("/searches", status_code=303)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        values = get_settings(db)
        return templates.TemplateResponse(request, "settings.html", context(request, db, secret_status=secret_status, schedule=scheduler_status(values.get("mock_mode") == "true")))

    @app.post("/settings")
    async def settings_save(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        data = SettingsIn(
            minimum_alert_score=int(form["minimum_alert_score"]),
            marketplace_id=form["marketplace_id"],
            max_results_per_query=int(form["max_results_per_query"]),
            scan_interval_minutes=int(form["scan_interval_minutes"]),
            collection_only_penalty=int(form["collection_only_penalty"]),
            meaningful_price_reduction_gbp=float(form["meaningful_price_reduction_gbp"]),
            telegram_enabled=parse_form_bool(form.get("telegram_enabled")),
            mock_mode=parse_form_bool(form.get("mock_mode")),
            log_level=form["log_level"],
            scheduler_enabled=parse_form_bool(form.get("scheduler_enabled")),
            local_timezone=form["local_timezone"],
        )
        update_settings(db, data.model_dump())
        configure_scheduler(app)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.post("/settings/remove-mock-data")
    async def settings_remove_mock_data(request: Request, db: Session = Depends(get_db)):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        removed = remove_mock_data(db)
        return RedirectResponse(
            f"/settings?mock_removed=1&listings={removed['listings']}&history={removed['price_history']}&scans={removed['scan_runs']}",
            status_code=303,
        )

    @app.post("/scheduler/pause")
    async def scheduler_pause(request: Request):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        pause_scheduler()
        return RedirectResponse("/", status_code=303)

    @app.post("/scheduler/resume")
    async def scheduler_resume(request: Request):
        if redirect := guard(request):
            return redirect
        form = await request.form()
        validate_csrf(request, dict(form))
        resume_scheduler()
        return RedirectResponse("/", status_code=303)

    @app.get("/logs", response_class=HTMLResponse)
    def logs_page(request: Request, db: Session = Depends(get_db), level: str = ""):
        if redirect := guard(request):
            return redirect
        return templates.TemplateResponse(request, "logs.html", context(request, db, lines=read_recent_logs(level), level=level))

    @app.get("/logs/download")
    def logs_download(request: Request):
        if redirect := guard(request):
            return redirect
        return Response(LOG_FILE.read_text(encoding="utf-8") if LOG_FILE.exists() else "", media_type="text/plain", headers={"Content-Disposition": "attachment; filename=audio_salvage_hunter.log"})

    @app.get("/health")
    @app.get("/health/live")
    def health_live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready(db: Session = Depends(get_db)):
        try:
            db.query(func.count(ListingRecord.id)).scalar()
            return {"status": "ready", "database": "ok"}
        except Exception as exc:
            return JSONResponse({"status": "not_ready", "database": str(exc)}, status_code=503)

    @app.get("/api/listings")
    def api_listings(request: Request, db: Session = Depends(get_db), limit: int = 100):
        require_login(request)
        rows = listing_query(db, dict(request.query_params)).limit(min(limit, 500)).all()
        return [{k: v for k, v in row.__dict__.items() if not k.startswith("_")} for row in rows]

    @app.get("/api/listings/{item_id}")
    def api_listing(request: Request, item_id: str, db: Session = Depends(get_db)):
        require_login(request)
        row = db.query(ListingRecord).filter_by(item_id=item_id).one_or_none()
        if not row:
            raise HTTPException(404, "Listing not found")
        return {k: v for k, v in row.__dict__.items() if not k.startswith("_")}

    @app.post("/api/scans", response_model=ScanOut)
    def api_scan(request: Request, payload: ScanRequest, db: Session = Depends(get_db)):
        require_login(request)
        if scan_status()["running"]:
            raise HTTPException(409, "Another scan is already running")
        scan = create_scan(db, payload.mode, payload.query_group, payload.custom_query, payload.notifications_enabled)
        start_scan_background(app, scan.id)
        return scan

    @app.get("/api/scans/{scan_id}", response_model=ScanOut)
    def api_scan_get(request: Request, scan_id: int, db: Session = Depends(get_db)):
        require_login(request)
        scan = db.get(ScanRunRecord, scan_id)
        if not scan:
            raise HTTPException(404, "Scan not found")
        return scan

    @app.get("/api/donors", response_model=list[DonorOut])
    def api_donors(request: Request, db: Session = Depends(get_db)):
        require_login(request)
        return db.query(DonorRecord).limit(500).all()

    @app.post("/api/donors", response_model=DonorOut)
    def api_donor_create(request: Request, payload: DonorIn, db: Session = Depends(get_db)):
        require_login(request)
        donor = apply_donor(DonorRecord(manufacturer=payload.manufacturer, model=payload.model), payload)
        db.add(donor)
        db.commit()
        db.refresh(donor)
        return donor

    @app.put("/api/donors/{donor_id}", response_model=DonorOut)
    def api_donor_update(request: Request, donor_id: int, payload: DonorIn, db: Session = Depends(get_db)):
        require_login(request)
        donor = db.get(DonorRecord, donor_id)
        if not donor:
            raise HTTPException(404, "Donor not found")
        apply_donor(donor, payload)
        db.commit()
        db.refresh(donor)
        return donor

    @app.delete("/api/donors/{donor_id}")
    def api_donor_delete(request: Request, donor_id: int, db: Session = Depends(get_db)):
        require_login(request)
        donor = db.get(DonorRecord, donor_id)
        if donor:
            db.delete(donor)
            db.commit()
        return {"deleted": bool(donor)}

    @app.get("/api/settings")
    def api_settings(request: Request, db: Session = Depends(get_db)):
        require_login(request)
        return get_settings(db)

    @app.put("/api/settings")
    def api_settings_put(request: Request, payload: SettingsIn, db: Session = Depends(get_db)):
        require_login(request)
        values = update_settings(db, payload.model_dump())
        configure_scheduler(app)
        return values


app = create_app()
