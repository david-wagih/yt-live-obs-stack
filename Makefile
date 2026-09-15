.PHONY: up down clean logs traffic errors slow incident

up:
	docker compose up --build -d

down:
	docker compose down

clean:
	docker compose down -v --remove-orphans

logs:
	docker compose logs -f

traffic:
	python3 loadgen/generate_traffic.py normal

errors:
	python3 loadgen/generate_traffic.py errors

slow:
	python3 loadgen/generate_traffic.py slow

incident:
	python3 loadgen/generate_traffic.py incident
