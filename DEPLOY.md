# Production Deployment Guide: Real-Time Anti-Mule Solution on GCP (GKE)

This document provides a step-by-step walkthrough for deploying the Real-Time Anti-Mule Solution to **Google Kubernetes Engine (GKE)** with **GitHub Actions CI/CD**.

---

## Prerequisites

1. **Google Cloud SDK (`gcloud`)** installed and logged in (`gcloud auth login`).
2. **`kubectl`** CLI installed.
3. An active **GCP Project** with billing enabled.
4. A **GitHub Repository** containing this codebase.

---

## Step 1: One-Time GCP Infrastructure Setup

Run the automated setup script to create your GKE cluster, Artifact Registry, IAM service account, and Workload Identity Provider for GitHub Actions:

```bash
chmod +x scripts/gcp-setup.sh
./scripts/gcp-setup.sh <YOUR_GCP_PROJECT_ID> us-central1 <YOUR_GITHUB_OWNER/YOUR_REPO>
```

### What this creates:
- **GKE Autopilot Cluster**: `antimule-cluster` in `us-central1`
- **Artifact Registry Repository**: `us-central1-docker.pkg.dev/<PROJECT>/antimule`
- **Service Account**: `github-actions-gke@<PROJECT>.iam.gserviceaccount.com`
- **Workload Identity Federation**: Keyless security for GitHub Actions

---

## Step 2: Configure GitHub Repository Secrets

In your GitHub repository, navigate to **Settings > Secrets and variables > Actions** and add the following 3 secrets output by the setup script:

| Secret Name | Example Value | Description |
| :--- | :--- | :--- |
| `GCP_PROJECT_ID` | `my-anti-mule-project` | Your GCP Project ID |
| `GCP_SA_EMAIL` | `github-actions-gke@my-anti-mule-project.iam.gserviceaccount.com` | Service account email |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/12345/locations/global/workloadIdentityPools/github-pool/providers/github-provider` | OIDC resource provider |

---

## Step 3: First-Time Manual Deployment (Optional)

If you wish to deploy manually from your terminal before pushing to GitHub:

```bash
# 1. Connect kubectl to your GKE cluster
gcloud container clusters get-credentials antimule-cluster --region us-central1

# 2. Build and push Docker images
REGISTRY="us-central1-docker.pkg.dev/<YOUR_GCP_PROJECT_ID>/antimule"
gcloud auth configure-docker us-central1-docker.pkg.dev

docker build -t $REGISTRY/api-server:latest services/api
docker build -t $REGISTRY/dashboard:latest services/dashboard
docker build -t $REGISTRY/anomaly-detector:latest services/detector
docker build -t $REGISTRY/graph-analyzer:latest services/graph-analyzer
docker build -t $REGISTRY/data-generator:latest services/generator

docker push $REGISTRY/api-server:latest
docker push $REGISTRY/dashboard:latest
docker push $REGISTRY/anomaly-detector:latest
docker push $REGISTRY/graph-analyzer:latest
docker push $REGISTRY/data-generator:latest

# 3. Substitute project ID and apply Kubernetes manifests
find k8s/ -type f -name "*.yaml" -exec sed -i "s/your-gcp-project-id/<YOUR_GCP_PROJECT_ID>/g" {} +

kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/kafka/
kubectl apply -f k8s/redis/
kubectl apply -f k8s/neo4j/
kubectl apply -f k8s/api-server/
kubectl apply -f k8s/dashboard/
kubectl apply -f k8s/anomaly-detector/
kubectl apply -f k8s/graph-analyzer/
kubectl apply -f k8s/data-generator/
kubectl apply -f k8s/ingress.yaml
```

---

## Step 4: Automated CI/CD Deployments

Once your secrets are set in GitHub, **every git push to `main`** will automatically:
1. Validate code syntax and Kubernetes manifests.
2. Build all 5 application container images in parallel.
3. Push tagged images to Google Artifact Registry.
4. Apply Kubernetes manifests and perform zero-downtime rolling updates to GKE.

---

## Step 5: Verification & Accessing the Deployment

Check pod status in the `antimule` namespace:

```bash
kubectl get pods -n antimule
```

Expected output:
```text
NAME                                READY   STATUS    RESTARTS   AGE
anomaly-detector-75c8d76d4d-x891z   1/1     Running   0          2m
api-server-5d9f78b84d-2k89p         1/1     Running   0          2m
api-server-5d9f78b84d-l456m         1/1     Running   0          2m
dashboard-6b87654b9d-4m91x          1/1     Running   0          2m
dashboard-6b87654b9d-7n82y          1/1     Running   0          2m
data-generator-58679d64f6-8x12p     1/1     Running   0          2m
graph-analyzer-8479c94b79-99m1z     1/1     Running   0          2m
kafka-0                             1/1     Running   0          4m
neo4j-0                             1/1     Running   0          4m
redis-6c589bd485-p691z              1/1     Running   0          4m
zookeeper-0                         1/1     Running   0          4m
```

### Accessing the Load Balancer IP:
```bash
kubectl get ingress antimule-ingress -n antimule
```
Open the assigned `ADDRESS` in your web browser to view the live anti-mule intelligence dashboard!

---

## Monitoring and Logs

View real-time logs for any component:

```bash
# View anomaly detector ML logs
kubectl logs -n antimule deploy/anomaly-detector -f

# View graph analyzer Louvain clustering logs
kubectl logs -n antimule deploy/graph-analyzer -f

# View API server logs
kubectl logs -n antimule deploy/api-server -f
```
