.PHONY: up down clean logs traffic errors slow incident

# Override with `make CONTAINER_ENGINE=podman up` (or `export CONTAINER_ENGINE=podman`)
CONTAINER_ENGINE ?= docker

up:
	$(CONTAINER_ENGINE) compose up --build -d

down:
	$(CONTAINER_ENGINE) compose down

clean:
	$(CONTAINER_ENGINE) compose down -v --remove-orphans

logs:
	$(CONTAINER_ENGINE) compose logs -f

traffic:
	python3 loadgen/generate_traffic.py normal

errors:
	python3 loadgen/generate_traffic.py errors

slow:
	python3 loadgen/generate_traffic.py slow

incident:
	python3 loadgen/generate_traffic.py incident
