import copy
import logging
import multiprocessing
import numpy as np

from .batch_filter import BatchFilter
from gunpowder.batch import Batch
from gunpowder.coordinate import Coordinate
from gunpowder.producer_pool import ProducerPool
from gunpowder.volume import VolumeType, Volume

logger = logging.getLogger(__name__)

class Chunk(BatchFilter):
    '''Assemble a large batch by requesting smaller chunks upstream.
    '''

    def __init__(self, request, chunk_spec, cache_size=50, num_workers=20):

        self.chunk_spec_template = chunk_spec
        self.dims = self.chunk_spec_template.volumes[self.chunk_spec_template.volumes.keys()[0]].dims()

        for volume_type in self.chunk_spec_template.volumes:
            assert self.dims == self.chunk_spec_template.volumes[volume_type].dims(),\
                "Volumes of different dimensionalities cannot be handled by chunk"

        self.request = copy.deepcopy(request)
        self.num_workers = num_workers
        if num_workers > 1:
            self.workers = ProducerPool([ lambda i=i: self.__run_worker(i) for i in range(num_workers) ], queue_size=cache_size)

    def setup(self):
        self.__prepare_requests()
        if self.num_workers > 1:
            self.workers.start()

    def teardown(self):
        if self.num_workers > 1:
            self.workers.stop()

    def provide(self, request):

        batch = None
        for i in range(self.num_requests):
            # get a chunk
            # chunk = self.get_upstream_provider().request_batch(chunk_request)
            if self.num_workers > 1:
                chunk = self.workers.get()
            else:
                chunk_request = self.requests.get()
                chunk = self.get_upstream_provider().request_batch(chunk_request)

            if batch is None:
                batch = self.__setup_batch(request, chunk)

            # fill returned chunk into batch
            for (volume_type, volume) in chunk.volumes.items():
                self.__fill(batch.volumes[volume_type].data, volume.data,
                            request.volumes[volume_type], volume.roi)

        return batch

    def __setup_batch(self, request, chunk_batch):

        batch = Batch()
        for (volume_type, roi) in request.volumes.items():
            if volume_type == VolumeType.PRED_AFFINITIES or volume_type == VolumeType.GT_AFFINITIES:
                shape = (3,)+ roi.get_shape()
            else:
                shape = roi.get_shape()

            interpolate = {
                VolumeType.RAW: True,
                VolumeType.GT_LABELS: False,
                VolumeType.GT_AFFINITIES: False,
                VolumeType.GT_MASK: False,
                VolumeType.PRED_AFFINITIES: False,
            }[volume_type]

            batch.volumes[volume_type] = Volume(data=np.zeros(shape),
                                                roi=roi,
                                                resolution=chunk_batch.volumes[VolumeType.RAW].resolution,
                                                interpolate=interpolate)
        return batch

    def __fill(self, a, b, roi_a, roi_b):
        logger.debug("filling " + str(roi_b) + " into " + str(roi_a))

        common_roi = roi_a.intersect(roi_b)
        if common_roi is None:
            return

        common_in_a_roi = common_roi - roi_a.get_offset()
        common_in_b_roi = common_roi - roi_b.get_offset()

        slices_a = common_in_a_roi.get_bounding_box()
        slices_b = common_in_b_roi.get_bounding_box()

        if len(a.shape) > len(slices_a):
            slices_a = (slice(None),)*(len(a.shape) - len(slices_a)) + slices_a
            slices_b = (slice(None),)*(len(b.shape) - len(slices_b)) + slices_b

        a[slices_a] = b[slices_b]

    def __run_worker(self, i):
        chosen_request = self.requests.get()
        return self.get_upstream_provider().request_batch(chosen_request)

    def __prepare_requests(self):
        # prepare all request which chunk will require and store them in queue
        self.requests = multiprocessing.Queue(maxsize=0)

        logger.info("batch with spec " + str(self.request) + " requested")

        # minimal stride is smallest shape in template volumes because they are all centered
        min_stride = self.chunk_spec_template.get_common_roi().get_shape()

        # initial shift required per volume to be at beginning of its requested roi
        all_initial_offsets = []
        for (volume_type, roi) in self.chunk_spec_template.volumes.items():
            all_initial_offsets.append(self.request.volumes[volume_type].get_begin() - roi.get_begin())
        begin = np.min(all_initial_offsets, axis=0)

        # max offsets required per volume to cover their entire requested roi
        all_max_offsets = []
        for (volume_type, roi) in self.chunk_spec_template.volumes.items():
            all_max_offsets.append(self.request.volumes[volume_type].get_end()-self.chunk_spec_template.volumes[volume_type].get_shape())
        end = np.max(all_max_offsets, axis=0) + min_stride

        offset = np.array(begin)
        while (offset < end).all():

            # create a copy of the requested batch spec
            chunk_request = copy.deepcopy(self.request)
            max_strides = []
            # change size and offset of the batch spec
            for volume_type, roi in self.chunk_spec_template.volumes.items():
                chunk_request.volumes[volume_type] = roi + Coordinate(offset)
                # adjust stride to be as large as possible. Chunk roi lies either:
                #   in front and within roi, then max stride shifts chunk roi to begin of request roi
                #   behind requested roi, ten max stride shifts chunk roi to end of ALL rois in request
                # finally, clip max_stride s.t. it is not smaller than min_stride
                max_stride = np.zeros([3])
                for dim in range(roi.dims()):
                    if self.request.volumes[volume_type].get_end()[dim] > chunk_request.volumes[volume_type].get_end()[dim]:
                        max_stride[dim] = self.request.volumes[volume_type].get_begin()[dim] - chunk_request.volumes[volume_type].get_begin()[dim]
                    else:
                        max_stride[dim] = end[dim] - offset[dim]
                max_strides.append(max_stride.clip(min_stride))

            stride = np.min(max_strides, axis=0)

            logger.info("requesting chunk " + str(chunk_request))
            self.requests.put(chunk_request)

            for d in range(self.dims):
                offset[d] += stride[d]
                if offset[d] >= end[d]:
                    if d == self.dims - 1:
                        break
                    offset[d] = begin[d]
                else:
                    break

        self.num_requests = int(self.requests.qsize())