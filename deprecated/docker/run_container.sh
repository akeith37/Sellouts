#!/bin/bash

# Allow Docker containers to access the X11 display
xhost +local:docker

# Run the container with DISPALY and GUI support
docker run -it \
    --rm \
    --env DISPLAY=$DISPLAY \
    --volume /tmp/.X11-unix:/tmp/.X11-unix \
    --device /dev/dri \
    --name sellouts_container \
    sellouts-playwright
