#!/bin/bash
docker stop sellouts-container 2>/dev/null
docker rm sellouts-container 2>/dev/null
docker rmi sellouts-playwright 2>/dev/null
