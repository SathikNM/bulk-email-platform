"""Inbound SMTP receiver for bounces (run: python -m app.workers.bounce_server).

Listens on port 25 and accepts mail ONLY for signed VERP addresses (bounces+<id>.<sig>@<bounce domain>)
on the bounce subdomains configured on direct-delivery accounts. Everything else is rejected at RCPT,
so the server can never relay mail or receive anything other than bounces.
"""
import asyncio
import logging
import os
import time

from aiosmtpd.controller import Controller

from app.db.session import worker_session
from app.services import bounces

log = logging.getLogger("bounce_server")
MAX_SIZE = 2 * 1024 * 1024


class BounceHandler:
    def __init__(self):
        self._domains: set[str] = set()
        self._loaded = 0.0

    def domains(self) -> set[str]:
        if time.time() - self._loaded > 60:
            db = worker_session(system=True)
            try:
                self._domains = bounces.bounce_domains(db)
            finally:
                db.close()
            self._loaded = time.time()
        return self._domains

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        local, _, domain = address.lower().rpartition("@")
        if domain not in self.domains() or not local.startswith(bounces.LOCAL_PREFIX):
            return "550 5.7.1 Relaying denied"
        if bounces.parse_verp(address) is None:
            return "550 5.1.1 No such mailbox"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        if len(envelope.content) > MAX_SIZE:
            return "552 5.3.4 Message too big"
        loop = asyncio.get_running_loop()
        for rcpt in envelope.rcpt_tos:
            outcome = await loop.run_in_executor(None, self._apply, rcpt, envelope.original_content or envelope.content)
            log.info("bounce for %s: %s", rcpt, outcome)
        return "250 OK"

    @staticmethod
    def _apply(rcpt: str, raw: bytes) -> str:
        db = worker_session(system=True)
        try:
            out = bounces.process(db, rcpt, raw)
            db.commit()
            return out
        except Exception:
            db.rollback()
            log.exception("failed to process bounce")
            return "error"
        finally:
            db.close()


def build(host: str = "0.0.0.0", port: int = 25) -> Controller:
    hostname = os.environ.get("BOUNCE_HOSTNAME", "mail.localhost")
    return Controller(BounceHandler(), hostname=host, port=port, server_hostname=hostname,
                      data_size_limit=MAX_SIZE, ident="BEP bounce receiver")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ctl = build(port=int(os.environ.get("BOUNCE_PORT", "25")))
    ctl.start()
    log.info("bounce receiver listening on %s:%s", ctl.hostname, ctl.port)
    try:
        while True:
            time.sleep(3600)
    finally:
        ctl.stop()
