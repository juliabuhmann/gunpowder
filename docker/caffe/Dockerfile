FROM nvidia/cuda:8.0-cudnn6-devel-ubuntu16.04
LABEL maintainer jfunke@iri.upc.edu

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        wget \
        libatlas-base-dev \
        libboost-all-dev \
        libgflags-dev \
        libgoogle-glog-dev \
        libhdf5-serial-dev \
        libleveldb-dev \
        liblmdb-dev \
        libopencv-dev \
        libprotobuf-dev \
        libsnappy-dev \
        protobuf-compiler \
        python-dev \
        python-numpy \
        python-pip \
        python-setuptools \
        python-scipy && \
    rm -rf /var/lib/apt/lists/*

ENV CAFFE_ROOT=/src/caffe
ENV CAFFE_REPOSITORY=https://github.com/naibaf7/caffe.git
ENV CAFFE_REVISION=02310e1e73b5724b94784f4020bb8f118020d4f1

WORKDIR $CAFFE_ROOT
RUN git clone ${CAFFE_REPOSITORY} . && \
    git checkout ${CAFFE_REVISION}
RUN pip install --upgrade pip && \
    for req in wheel $(cat python/requirements.txt) pydot; do pip install $req; done

WORKDIR $CAFFE_ROOT/build
RUN cmake -DUSE_INDEX_64=1 -DUSE_CUDA=1 -DUSE_LIBDNN=1 -DUSE_CUDNN=1 -DUSE_OPENMP=0 -DUSE_GREENTEA=0 .. && \
    make --jobs $(nproc)

# setup env to find pycaffe

ENV PYCAFFE_ROOT $CAFFE_ROOT/python
ENV PYTHONPATH $PYCAFFE_ROOT:$PYTHONPATH
ENV PATH $CAFFE_ROOT/build/tools:$PYCAFFE_ROOT:$PATH
RUN echo "$CAFFE_ROOT/build/lib" >> /etc/ld.so.conf.d/caffe.conf && \
    ldconfig

WORKDIR /run
