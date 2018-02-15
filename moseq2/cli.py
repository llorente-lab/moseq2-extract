from moseq2.io.video import get_movie_info, load_movie_data
from moseq2.io.image import write_image, read_image
from moseq2.extract.extract import extract_chunk
from moseq2.extract.proc import apply_roi, get_roi, get_bground_im_file
from moseq2.util import load_metadata, gen_batch_sequence, load_timestamps
import click
import json
import os
import h5py
import tqdm
import cv2
import numpy as np

@click.command(name="extract")
@click.argument('input-file',type=click.Path(exists=True))
@click.option('--crop-size','-c',default=(80,80),type=tuple)
@click.option('--roi-dilate',default=10,type=int)
@click.option('--roi-shape',default='ellipse',type=str)
@click.option('--roi-index',default=0,type=int)
@click.option('--min-height',default=10,type=int)
@click.option('--max-height',default=100,type=int)
@click.option('--fps',default=30,type=int)
@click.option('--flip-file',default=None)
@click.option('--em-tracking',is_flag=True)
@click.option('--prefilter-space',default=(3,),type=tuple)
@click.option('--prefilter-time',default=(),type=tuple)
@click.option('--chunk-size',default=1000,type=int)
@click.option('--chunk-overlap',default=10,type=int)
@click.option('--output-dir',default=None)
@click.option('--write-movie',default=True,type=bool)
@click.option('--temp-dir',default=None)
def extract(input_file,crop_size,roi_dilate,roi_shape,roi_index,min_height,max_height,
            fps,flip_file,em_tracking,prefilter_space,prefilter_time,
            chunk_size,chunk_overlap,output_dir,write_movie,temp_dir):

    # get the basic metadata

    video_metadata=get_movie_info(input_file)
    nframes=video_metadata['nframes']
    extraction_metadata=load_metadata(os.path.join(os.path.dirname(input_file),'metadata.json'))
    timestamps=load_timestamps(os.path.join(os.path.dirname(input_file),'depth_ts.txt'),col=0)

    scalars=['centroid_x','centroid_y','angle','width',
             'length','height_ave','velocity_mag',
             'velocity_theta','area','velocity_mag_3d']

    frame_batches=list(gen_batch_sequence(nframes,chunk_size,chunk_overlap))

    # set up the output directory

    if not output_dir:
        output_dir=os.path.join(os.path.dirname(input_file),'proc')

    if not os.path.exists(output_dir):
        os.path.makedirs(output_dir)

    # prepare an hdf5 file for all the resulting output, dump videos in a temp directory to be stitched later

    results_file=os.path.join(output_dir,'results.h5')
    scalar_dsets=[]

    # get the background and roi, which will be used across all batches

    print('Getting background...')
    bground_im=get_bground_im_file(input_file)

    write_image(os.path.join(output_dir,'bground.tiff'),bground_im,scale=True)
    first_frame=load_movie_data(input_file,0)

    write_image(os.path.join(output_dir,'first_frame.tiff'),first_frame,scale=True,scale_factor=(650,750))

    if roi_shape[0].lower()=='e':
        strel_dilate=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(roi_dilate,roi_dilate))
    elif roi_shape[0].lower()=='r':
        strel_dilate=cv2.getStructuringElement(cv2.MORPH_RECT,(roi_dilate,roi_dilate))
    else:
        strel_dilate=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(roi_dilate,roi_dilate))

    print('Getting roi...')
    rois,_,_,_,_=get_roi(bground_im,strel_dilate=strel_dilate)
    roi=rois[roi_index]

    write_image(os.path.join(output_dir,'roi.tiff'),roi,scale=True,dtype='uint8')

    # farm out the batches and write to an hdf5 file

    with h5py.File(os.path.join(output_dir,'results.h5'),'w') as f:
        scalars_dsets=[]
        for i in range(len(scalars)):
            f.create_dataset('scalars/{}'.format(scalars[i]),(nframes,),'float32',compression='gzip')

        f.create_dataset('frames',(nframes,crop_size[0],crop_size[1]),'i1',compression='gzip')

        for i,frame_range in enumerate(tqdm.tqdm(frame_batches, desc='Processing batches')):
            raw_frames=load_movie_data(input_file,frame_range)
            raw_frames=bground_im-raw_frames
            raw_frames[np.logical_or(raw_frames<min_height,raw_frames>max_height)]=0
            raw_frames=raw_frames.astype('uint8')
            raw_frames=apply_roi(raw_frames,roi)

            results=extract_chunk(raw_frames,use_em_tracker=em_tracking,prefilter_space=prefilter_space,
                                  prefilter_time=prefilter_time,min_height=min_height,max_height=max_height,
                                  flip_classifier=flip_file,crop_size=crop_size)

            # if desired, write out a movie

            for scalar in scalars:
                f['scalars/{}'.format(scalar)][frame_range]=results['scalars'][scalar]
            f['frames'][frame_range]=results['depth_frames']



if __name__ == '__main__':
    extract()
