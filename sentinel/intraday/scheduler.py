from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from sentinel.db import create_db_engine
from sentinel.models import TradingCalendar
from sentinel.intraday.snapshots import capture_intraday_snapshot
from sentinel.intraday.engine import run_tomorrow_star_scan
from sentinel.intraday.trades import update_intraday_trades, monitor_and_close_intraday_trades
from sentinel.intraday.notifiers import TelegramNotifier
from sentinel.config import Settings

logger = logging.getLogger(__name__)

class IntradayScheduler:
    """
    Scheduler for automated intraday trading strategy tasks.
    """
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_db_engine(database_url)
        self.scheduler = BlockingScheduler()
        self.settings = Settings()
        
        # Configure notifier if settings available
        self.notifier = None
        # Priority: Settings fields (likely from .env)
        token = self.settings.tg_token
        chat_id = self.settings.tg_chat_id
        
        # Fallback to known hardcoded defaults if not in env
        if not token:
            token = "5675544561:AAG7ANUJgyljr84SAKB4OAcf_WYTS_nw-jc"
        if not chat_id:
            chat_id = "-5018674933"

        if token and chat_id:
            self.notifier = TelegramNotifier(token, chat_id)

    def is_trading_day(self, session: Session, check_date: date) -> bool:
        """Check if today is a trading day in TWSE."""
        stmt = select(TradingCalendar.is_trading_day).where(
            and_(
                TradingCalendar.exchange == "TWSE",
                TradingCalendar.calendar_date == check_date
            )
        )
        result = session.execute(stmt).scalar()
        if result is None:
            # Fallback if calendar data is missing (Weekend check)
            weekday = check_date.weekday()
            return weekday < 5
        return bool(result)

    def _execute_job(self, job_func, *args, **kwargs):
        """Wrapper to check trading day and catch errors."""
        today = date.today()
        from sqlalchemy.orm import Session
        with Session(self.engine) as session:
            if not self.is_trading_day(session, today):
                logger.info(f"Skipping {job_func.__name__} - {today} is not a trading day.")
                return

            try:
                logger.info(f"Starting job: {job_func.__name__} at {datetime.now()}")
                job_func(session, *args, **kwargs)
                logger.info(f"Completed job: {job_func.__name__}")
            except Exception as e:
                logger.exception(f"Error in job {job_func.__name__}: {e}")
                if self.notifier:
                    self.notifier.send_message(f"❌ <b>Scheduler Error</b>\nJob: {job_func.__name__}\nError: {str(e)}")

    def run_snapshot(self, snapshot_time: Optional[str] = None):
        """Job: Capture intraday snapshot."""
        def job(session):
            time_str = snapshot_time or datetime.now().strftime("%H:%M")
            count = capture_intraday_snapshot(session, snapshot_time=time_str)
            logger.info(f"Snapshot Captured at {time_str}: {count} stocks.")
        self._execute_job(job)

    def run_strategy(self):
        """Job: Run strategy scan at 13:00."""
        def job(session):
            results = run_tomorrow_star_scan(session)
            if results and self.notifier:
                self.notifier.send_scan_results(results)
            logger.info(f"Strategy Scan completed: {len(results)} results found.")
        self._execute_job(job)

    def run_trade_settlement(self, force_close: bool = False):
        """Job: Monitor for SL/TP or execute 09:30 force closure."""
        def job(session):
            count = monitor_and_close_intraday_trades(session, threshold=0.02, force_close=force_close)
            if count > 0 and self.notifier:
                self.notifier.send_message(f"🔔 <b>模擬交易平倉通知</b>\n自動結算已完成，共計平倉 {count} 檔個股。")
            logger.info(f"Monitor job executed: {count} trades closed.")
        self._execute_job(job)

    def start(self):
        """Start the scheduler."""
        # Schedule jobs
        # 09:00 - 09:29: Every 1 minute, check SL/TP
        self.scheduler.add_job(
            self.run_trade_settlement, 
            'cron', 
            hour=9, 
            minute='0-29', 
            id='monitor_sl_tp', 
            kwargs={'force_close': False}
        )
        
        # 09:30: Force close all
        self.scheduler.add_job(
            self.run_trade_settlement, 
            'cron', 
            hour=9, 
            minute=30, 
            id='force_close_trades', 
            kwargs={'force_close': True}
        )
        
        # 12:00: Capture volume snapshot for strategy baseline
        self.scheduler.add_job(
            self.run_snapshot,
            'cron',
            hour=12,
            minute=0,
            id='capture_12pm_snapshot',
            kwargs={'snapshot_time': '12:00'}
        )
        
        self.scheduler.add_job(self.run_strategy, 'cron', hour=13, minute=0, id='run_strategy')
        
        logger.info("Intraday Scheduler started.")
        logger.info("Scheduled: 09:00-09:29 (SL/TP Monitor), 09:30 (Cutoff), 12:00 (Baseline Snapshot), 13:00 (Tomorrow's Star Strategy)")
        
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")
