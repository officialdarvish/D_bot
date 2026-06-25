# Docker build fix

The default Dockerfile now uses the already-exported static admin UI from `frontend_out/`, so the production image can be built without running `npm install` or `next build` inside Docker.

Build and push:

```bash
docker build --no-cache -t darvish021/d_bot:latest .
docker push darvish021/d_bot:latest
```

If you edit the frontend source and want Docker to rebuild the Next.js UI from source, use:

```bash
docker build --no-cache -f Dockerfile.fullbuild -t darvish021/d_bot:latest .
```
