# Deployment Information

## Public URL
https://k5-l3b-day14-vuongtoanminhhieu.onrender.com

## Platform
Render

## Test Commands

### Health & Readiness Check
```bash
curl https://k5-l3b-day14-vuongtoanminhhieu.onrender.com/health
curl https://k5-l3b-day14-vuongtoanminhhieu.onrender.com/ready
```

### API Test (with authentication)
```bash
curl -X POST https://k5-l3b-day14-vuongtoanminhhieu.onrender.com/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

## Environment Variables Set
- `PORT`
- `REDIS_URL`
- `AGENT_API_KEY`
- `ENVIRONMENT`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
