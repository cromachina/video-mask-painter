# Video Mask Painter

This tool lets you paint masks on videos and then export the mask as another video, or apply the mask as a mosaic to a copy of the original video.

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/67693447-80e4-4d58-a1e0-ce795337aa50" />

## Why

I use this to add mosaics to my painting timelapse videos.
It's a lot more efficient and accurate than creating and moving limited effect shapes with something like Kdenlive.
The output rendering is also an order of magnitude faster than Kdenlive (the GPU is used to compute the mosaic).

## How to use
Select `File -> Open Video as New Project` to begin working on a video.
You can select or seek to a frame and create a keyframe which you can paint a mask on. That keyframe is applied to all frames after it until the next keyframe is made.
You can clone, cut, copy, and paste keyframes as well. There is also a function to automatically create a new or cloned keyframe when you start painting on a different frame.
The tool automatically saves to a temporary location if the current project has not been saved, so that you can recover work in case of an error.

## Shortcuts

Almost every action can be configured with multiple shortcuts.
There is no checking to see if any shortcuts of different actions are conflicting. If there is a conflict, both shortcuts will trigger,
but the order that conflicting shortcuts are triggered is undefined, so you should not rely on this to try to make a compound action.

## Run/install

### Nix
This project is a nix flake, so you can use `nix run` with it.

### Any OS
This project can be installed with python pip after downloading the source, using `pip install -e .` in the source directory.
You might need FFMPEG to be installed for OpenCV to be able to open video files other than MP4.

## TODO
- Maybe get pen pressure to work, somehow.
- Windows pyinstaller build.
- Linux appimage build.
