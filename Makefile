MC_DIR := $${HOME}/Documents/MINECRAFT_SERVERS/PaperMC
PLUGIN_VERSION := 1.21.4

update:
	./gradlew clean build -Pversion=$(PLUGIN_VERSION) && \
	rm -fr  $(MC_DIR)/plugins/JuicyRaspberryPie && \
	rm -f $(MC_DIR)/plugins/juicyraspberrypie*.jar && \
	cp build/libs/juicyraspberrypie-$(PLUGIN_VERSION).jar $(MC_DIR)/plugins/

run:
	cd $(MC_DIR) && \
	screen -dmS minecraft java -Xmx8G -Xms8G -jar paper.jar

stop:
	cd $(MC_DIR) && \
	screen -S minecraft -X stuff "stop\015"

restart:
	-make stop
	sleep 5
	make run

update-restart:
	make update
	make restart
