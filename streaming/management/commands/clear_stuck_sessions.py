"""Clears any Session stuck in STARTING/ACTIVE — e.g. after a test client
(jetson_mock, mock_flutter_answer.py, test_full_flow.py) got killed instead
of cleanly running stop_stream through to stream_stopped. This deployment
only allows one concurrent session (streaming/services.py start_session),
so a stuck row blocks every new start_session call with "Another session
already running on this device?" until it's cleared.

Usage:
    python manage.py clear_stuck_sessions          # inside the venv/container
    docker exec g-lab-backend-1 python manage.py clear_stuck_sessions
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from streaming.models import Session


class Command(BaseCommand):
    help = "Marks any STARTING/ACTIVE session as COMPLETED, unblocking start_session."

    def handle(self, *args, **options):
        stuck = Session.objects.filter(status__in=[Session.Status.STARTING, Session.Status.ACTIVE])

        if not stuck.exists():
            self.stdout.write("No stuck sessions.")
            return

        for session in stuck:
            self.stdout.write(f"clearing {session.session_id} ({session.status}, started {session.started_at})")

        count = stuck.update(status=Session.Status.COMPLETED, ended_at=timezone.now())
        self.stdout.write(self.style.SUCCESS(f"cleaned {count} session(s)"))
