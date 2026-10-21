# Python Backend Challenge: Notification Service

## El Reto
Implementar un servicio de notificaciones que actúe como mediador entre los clientes y un proveedor externo. Tu objetivo es diseñar una solución sólida que pase la suite de validación de rendimiento y resiliencia.

```mermaid 
flowchart LR
    A[Client] --> B(Your App)
    B --> C[Notification Provider]
    
    style B fill:#1a2a6c,stroke:#fff,stroke-width:2px,color:#fff
```

## Contrato de API
Para que la suite de tests (k6) pueda validar tu solución, debes implementar estrictamente los siguientes endpoints en el **puerto 5000**:

- **Registro de Solicitud:** `POST /v1/requests`  
  Cuerpo (JSON): `{"to": "string", "message": "string", "type": "email|sms|push"}`  
  Respuesta: `201 Created` con JSON `{"id": "string"}`.

- **Procesamiento de Envío:** `POST /v1/requests/{id}/process`  
  Descripción: Lanza la integración con el proveedor externo.  
  Respuesta: `200 OK` o `202 Accepted`.

- **Consulta de Estado:** `GET /v1/requests/{id}`  
  Respuesta: `200 OK` con JSON `{"id": "string", "status": "queued|processing|sent|failed"}`.

---

## Integración con el Provider
El servicio de notificaciones está disponible en `localhost:3001`. Requiere el encabezado de seguridad: `X-API-Key: test-dev-2026`.

- **Notificaciones:** `/v1/notify` (Esquema definido en los docs del provider).
- **Documentación:** Puedes consultar los Swagger Docs en `http://localhost:3001/docs`.

---

## Ejecución y Evaluación

1. **Levantar infraestructura:** `docker-compose up -d provider influxdb grafana`
2. **Tu aplicación:** `docker-compose up -d --build app`
3. **Validación (k6):** `docker-compose run --rm load-test`
4. **Resultados:** Visualiza el scorecard en tiempo real en [Grafana (localhost:3000)](http://localhost:3000/d/backend-performance-scorecard/)

*Se valorará la robustez frente a errores inesperados, la calidad de la implementación y la arquitectura del pipeline de procesamiento.*

## Implementation

The application now persists requests and dispatch intent in SQLite and processes
them with bounded asynchronous workers. It preserves the API and provider/k6
contracts above. A named Docker volume retains data across container recreation.

```sh
docker compose up -d --build --wait app influxdb grafana
docker compose run --rm load-test
```

The supplied provider can deliver only a few notifications per second. A load
test may accept thousands of requests quickly; leave the application running
until its durable backlog drains. HTTP checks alone do not prove delivery.

- [Architecture, crash recovery and delivery guarantees](docs/architecture.md)
- [Tests, load validation and eventual-delivery verification](docs/testing.md)
- [Measured validation results](docs/validation.md)
- [Final engineering audit](docs/audit.md)
- [Environment configuration example](.env.example)

For local development without Docker, use Python 3.12, install
`app/requirements-dev.txt`, export `NOTIFY_PROVIDER_API_KEY=test-dev-2026`, and run
`uvicorn main:app --app-dir app --host 0.0.0.0 --port 5000`. Other settings use the
`NOTIFY_` prefix; see `app/notification_service/config.py`. The application fails
startup when workers are enabled without provider credentials.

Host port 5000 can conflict with macOS AirPlay. The testing guide documents a
temporary host-port override that preserves internal port 5000 and the original
load tests. No commits or pushes are required to run the implementation.
