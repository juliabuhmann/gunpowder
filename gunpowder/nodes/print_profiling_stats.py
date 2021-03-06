import logging

from .batch_filter import BatchFilter

logger = logging.getLogger(__name__)

class PrintProfilingStats(BatchFilter):

    def process(self, batch, request):
        logger.info(batch.profiling_stats)
