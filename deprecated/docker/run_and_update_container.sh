#!/bin/bash

IMAGE_NAME="sellouts-playwright"
CONTAINER_NAME="sellouts-container"
HOST_SCRIPT_PATH="$HOME/Alertix/sellouts_playwright.py"
CONTAINER_SCRIPT_PATH="/app/sellouts.py"

# 1. Check if the container is already running
RUNNING_CONTAINER=$(docker ps -q -f name="$CONTAINER_NAME")

# 2. If not running, check if it exists (stopped)
if [ -z "$RUNNING_CONTAINER" ]; then
    EXISTING_CONTAINER=$(docker ps -aq -f name="$CONTAINER_NAME")

    if [ -z "$EXISTING_CONTAINER" ]; then
        echo "Starting new container from image $IMAGE_NAME..."
        docker run -dit --name "$CONTAINER_NAME" \
            -e DISPLAY=:0 \
            -v /tmp/.X11-unix:/tmp/.X11-unix \
            --network host \
            "$IMAGE_NAME" bash
    else
        echo "Starting existing container..."
        docker start "$CONTINER_NAME"
    fi
else
    echo  "Container $CONTAINER_NAME is already running."
fi

# 3. Install chromium once the container is running and before the script runs
#docker exec "$CONTAINER_NAME" playwright install chromium

# 4. Copy the updated Python script into the container
echo "Copying updated script into the container..."
docker cp "$HOST_SCRIPT_PATH" "$CONTAINER_NAME:$CONTAINER_SCRIPT_PATH"

# 5. Run the script inside the container
echo "Running the script..."
docker exec -it "$CONTAINER_NAME" python3 "$CONTAINER_SCRIPT_PATH"
