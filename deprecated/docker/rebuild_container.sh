#!/bin/bash
docker build --no-cache -t sellouts-playwright .
docker run -dit --name sellouts-container sellouts-playwright bash
docker exec -it sellouts-container bash
