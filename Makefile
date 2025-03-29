# Makefile for Minecraft server management for Ubuntu or MacOS
#  requires GNU Make
#  requires screen
# Author: Naohiro Tsuji

# Minecraft server settings
MC_DIR := $(HOME)/MINECRAFT_SERVERS/PaperMC
SERVER_FILE := paper.jar

ifeq ($(OS),Windows_NT)
    RUN_SERVER_CMD = cd $(MC_DIR) && java -Xmx8G -Xms8G -jar $(SERVER_FILE)
    STOP_SERVER_CMD = echo "Stop command for Windows not implemented. Please stop the server manually."
else
    RUN_SERVER_CMD = cd $(MC_DIR) && screen -dmS minecraft java -Xmx8G -Xms8G -jar $(SERVER_FILE) && echo "Minecraft server started successfully."
    STOP_SERVER_CMD = cd $(MC_DIR) && \
        if screen -list | grep -q minecraft; then \
            screen -S minecraft -X stuff "stop\r" && sleep 5; \
        else \
            echo "No screen session found for 'minecraft'"; \
        fi
endif

.PHONY: runServer stopServer restartServer

runServer:  # Start the server
	@echo "Starting Minecraft server..."
    $(RUN_SERVER_CMD)

stopServer:  # Stop the server
	@echo "Stopping Minecraft server..."
    $(STOP_SERVER_CMD)

restartServer: stopServer runServer
