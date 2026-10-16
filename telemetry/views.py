from rest_framework import generics

from .models import AnalysisEvent
from .serializers import AnalysisEventSerializer


class SessionAnalysisListView(generics.ListAPIView):
    """GET /api/sessions/{session_id}/analysis/

    Replaces the `analysis` action formerly on streaming.SessionViewSet —
    moved here so the endpoint lives with the model/data path it serves.
    """

    serializer_class = AnalysisEventSerializer

    def get_queryset(self):
        return AnalysisEvent.objects.filter(session__session_id=self.kwargs["session_id"])
