.PHONY: up down seed logs ps scenario browser-load secrets-init secrets-check images k8s-secrets k8s-render k8s-dry-run k8s-up k8s-down disk prune deploy undeploy status

up:
	docker compose up -d --build --wait

down:
	docker compose down

seed:
	docker compose run --rm --build seed

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

scenarios/.venv/bin/python:
	python3 -m venv scenarios/.venv
	scenarios/.venv/bin/pip install -q -r scenarios/requirements.txt

# make scenario NAME=monday_peak  (TARGET=compose for the Compose stack, NAME unset lists scenarios)
scenario: scenarios/.venv/bin/python
	scenarios/.venv/bin/python scenarios/run_scenario.py $(NAME) --target $(or $(TARGET),k8s)

# make browser-load PROFILE=completer SESSIONS=5 CONCURRENCY=3  (PROFILE: completer, abandoner or assistant)
browser-load:
	@cd load/browser && { [ -d node_modules ] || npm install --no-audit --no-fund; } && node run.mjs --base-url $(or $(BASE_URL),http://localhost:8080) --profile $(or $(PROFILE),completer) --sessions $(or $(SESSIONS),3) --concurrency $(or $(CONCURRENCY),3)

secrets-init:
	@scripts/secrets.sh init

secrets-check:
	@scripts/secrets.sh check

IMAGES = web:services/web claims-api:services/claims-api llm-gateway:services/llm-gateway \
         payment-worker:services/payment-worker legacy-stub:services/legacy-stub \
         locust:load/locust seed:db

# Build and tag local images. Rancher Desktop (docker runtime) shares them with k3s.
images:
	@for i in $(IMAGES); do docker build -q -t gov-demo/$${i%%:*}:dev $${i#*:} || exit 1; done

# Create the app Secret from .env without writing values into manifests.
k8s-secrets:
	kubectl create namespace gov-demo --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n gov-demo create secret generic gov-demo-env --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n gov-demo create secret generic gov-demo-credentials --from-file=credentials.csv=db/out/credentials.csv --dry-run=client -o yaml | kubectl apply -f -

k8s-render:
	@kubectl kustomize k8s/

k8s-dry-run:
	kubectl apply -k k8s/ --dry-run=client
	kubectl apply -k k8s/ --dry-run=server

k8s-up:
	kubectl apply -k k8s/

k8s-down:
	kubectl delete -k k8s/

# Where disk goes: Docker usage, the filesystem behind it, the database and the biggest container logs.
disk:
	@echo "== docker usage"; docker system df
	@echo "== filesystem behind docker"; docker run --rm -v /var/lib/docker:/d:ro alpine df -h /d | tail -1
	@echo "== database"; kubectl exec -n gov-demo deploy/postgres -c postgres -- sh -c "psql -U $$POSTGRES_USER -d $$POSTGRES_DB -At -c \"select pg_size_pretty(pg_database_size(current_database()))\""
	@echo "== five largest container logs"; docker run --rm -v /var/lib/docker/containers:/c:ro alpine sh -c 'ls -l /c/*/*-json.log 2>/dev/null | awk "{printf \"%7.1f MB  %s\\n\", \$$5/1048576, \$$9}" | sort -rn | head -5'

# Reclaims build cache older than a day and dangling images. Dangling images are machine wide, not only this project.
prune:
	docker builder prune -f --filter until=24h
	docker image prune -f

# One command deploy to the current kubectl context, see docs/deploy.md.
#   make deploy                                        local cluster (Rancher Desktop, Docker Desktop, OrbStack, Colima)
#   make deploy REGISTRY=ghcr.io/you/gov-demo TAG=v1   any other cluster (builds amd64 and arm64 and pushes)
#   make deploy DRYRUN=yes                             preflight and plan only, changes nothing on the cluster
deploy:
	@scripts/deploy.sh $(if $(REGISTRY),--registry $(REGISTRY)) $(if $(TAG),--tag $(TAG)) $(if $(YES),--yes) $(if $(DRYRUN),--dry-run)

undeploy:
	@printf 'Delete namespace gov-demo on context "%s"? [y/N] ' "$$(kubectl config current-context)"; read a; [ "$$a" = y ] && kubectl delete namespace gov-demo

status:
	@kubectl get pods,svc,cronjob -n gov-demo; echo; kubectl get dynakube -A 2>/dev/null || true
