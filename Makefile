.PHONY: up up-gpu down logs model seed demo demo-fast test lint fixtures template validate dev admin \
	prod-up prod-down prod-logs prod-warm prod-demo deploy \
	laptop-up laptop-down edge-setup edge-cert tunnel-install tunnel-status tunnel-stop

up:
	docker compose up -d --build
	$(MAKE) model
	@echo "Готово: http://localhost:8000"

up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
	$(MAKE) model
	@echo "Готово (Ollama на GPU): http://localhost:8000"

down:
	docker compose down

logs:
	docker compose logs -f app

model:
	docker compose exec -T ollama ollama pull $${OLLAMA_MODEL:-qwen2.5:3b-instruct}

seed:
	docker compose exec -T app python -m app.seed

demo:
	docker compose exec -T app python -m app.seed --reset

demo-fast:
	docker compose exec -T app python -m app.seed --reset --fast

dev:
	uv run alembic upgrade head && uv run uvicorn app.main:app --reload

test:
	uv run pytest -q

lint:
	uv run ruff check --fix . && uv run ruff format .

fixtures:
	uv run python -m ml.make_fixtures

template:
	uv run python -m ml.make_template

validate:
	uv run python -m ml.validate

admin:
	uv run --group admin streamlit run admin/app.py

# ---------- сервер (см. docs/DEPLOY.md) ----------
PROD = docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.prod.yml
PROD_DIR ?= /opt/pulse

prod-up:
	$(PROD) up -d --build --remove-orphans
	m=$$(grep -s ^OLLAMA_MODEL= .env | cut -d= -f2); $(PROD) exec -T ollama ollama pull $${m:-qwen2.5:3b-instruct}
	$(MAKE) prod-warm
	@if ! $(PROD) exec -T db psql -U pulse -tAc "select 1 from users limit 1" 2>/dev/null | grep -q 1; then $(MAKE) prod-demo; fi
	@echo "Готово: https://$$(grep ^DOMAIN= .env | cut -d= -f2)"

prod-down:
	$(PROD) down

prod-logs:
	$(PROD) logs -f --tail=200 app caddy

prod-warm:
	$(PROD) exec -T app python -m app.services.llm.warm

prod-demo:
	$(PROD) exec -T app python -m app.seed --reset

deploy:
	@test -n "$(HOST)" || (echo "Укажите сервер: make deploy HOST=root@1.2.3.4" && exit 1)
	rsync -az --delete --exclude-from=deploy/rsync-exclude ./ $(HOST):$(PROD_DIR)/
	ssh $(HOST) 'cd $(PROD_DIR) && make prod-up'

# ---------- ноутбук + сервер-посредник (см. docs/DEPLOY.md) ----------
LAPTOP = docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.laptop.yml

laptop-up:
	$(LAPTOP) up -d --build --remove-orphans
	m=$$(grep -s ^OLLAMA_MODEL= .env | cut -d= -f2); $(LAPTOP) exec -T ollama ollama pull $${m:-qwen2.5:3b-instruct}
	$(LAPTOP) exec -T app python -m app.services.llm.warm
	@echo "Готово: http://localhost:8000 (снаружи — через туннель)"

laptop-down:
	$(LAPTOP) down

EDGE_USER ?= root

edge-setup:
	@test -n "$(EDGE)" -a -n "$(DOMAIN)" || (echo "Укажите: make edge-setup EDGE=1.2.3.4 DOMAIN=pulse.example.ru [EDGE_USER=pulse]" && exit 1)
	scp -i ~/.ssh/pulse_admin -o StrictHostKeyChecking=accept-new -r deploy/edge $(EDGE_USER)@$(EDGE):pulse-edge
	ssh -i ~/.ssh/pulse_admin $(EDGE_USER)@$(EDGE) "sudo bash pulse-edge/edge-setup.sh $(DOMAIN) '$$(cat ~/.ssh/pulse_tunnel.pub)'"

# Готовый сертификат на сервер-посредник, если Let's Encrypt не может достучаться до сервера по HTTP
edge-cert:
	@test -n "$(EDGE)" -a -n "$(CERT)" -a -n "$(KEY)" || (echo "Укажите: make edge-cert EDGE=1.2.3.4 CERT=fullchain.pem KEY=privkey.pem [EDGE_USER=pulse]" && exit 1)
	scp -i ~/.ssh/pulse_admin $(CERT) $(EDGE_USER)@$(EDGE):pulse-cert.pem
	scp -i ~/.ssh/pulse_admin $(KEY) $(EDGE_USER)@$(EDGE):pulse-key.pem
	ssh -i ~/.ssh/pulse_admin $(EDGE_USER)@$(EDGE) "sudo install -d -m 750 -g caddy /etc/caddy/certs /etc/caddy/tls.d \
		&& sudo install -m 644 pulse-cert.pem /etc/caddy/certs/domain.crt \
		&& sudo install -m 640 -g caddy pulse-key.pem /etc/caddy/certs/domain.key \
		&& rm pulse-cert.pem pulse-key.pem \
		&& echo 'tls /etc/caddy/certs/domain.crt /etc/caddy/certs/domain.key' | sudo tee /etc/caddy/tls.d/manual >/dev/null \
		&& sudo systemctl reload caddy"

tunnel-install:
	@test -n "$(EDGE)" || (echo "Укажите сервер: make tunnel-install EDGE=1.2.3.4" && exit 1)
	mkdir -p ~/.config/systemd/user
	sed 's/@EDGE@/$(EDGE)/' deploy/edge/pulse-tunnel.service > ~/.config/systemd/user/pulse-tunnel.service
	systemctl --user daemon-reload
	systemctl --user enable --now pulse-tunnel
	loginctl enable-linger $$USER
	@sleep 3; systemctl --user --no-pager status pulse-tunnel | head -5

tunnel-status:
	systemctl --user --no-pager status pulse-tunnel | head -12

tunnel-stop:
	systemctl --user disable --now pulse-tunnel
