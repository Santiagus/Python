# Deployment

Start point for this project is the previous project 04_Securing.

## Setup
#### Create Virtual Environment \
```python -m venv .venv```

#### Install PostgresSQL driver to comunicate with the database \
```pip install psycopg2-binary```

#### Install AWS CLI
```pip install awscli```

#### Update dependencies file
`$ pip freeze > requirements.txt`

**NOTE:** Remove `urllib3==2.0.7`, it causes a conflict

#### Create an AWS account and obtain an access key to be able to access AWS services programmatically. https://aws.amazon.com/

#### Install Docker
https://docs.docker.com/engine/install/debian/

**NOTE:** If using WSL is probable docker service is not running by default, just execute the following command to init it\
`$ sudo service docker start` 

To verify status run : \
`$ service docker status`

## Update hardcoded database URL
<details><summary>orders/repository/unit_of_work.py</summary>

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DB_URL = os.getenv('DB_URL')    # Pull URL form environment variable

assert DB_URL is not None, 'DB_URL environment variable needed.'

class UnitOfWork:
    def __init__(self):
        self.session_maker = sessionmaker(bind=create_engine(DB_URL))

    def __enter__(self):
        self.session = self.session_maker()
        return self
...
```
</details>

## Update hardcoded database URL
<details><summary>migrations/env.py</summary>

```python
import os
from logging.config import fileConfig
from sqlalchemy import create_engine
from sqlalchemy import pool
from alembic import context

def run_migrations_online():
"""...
"""
url = os.getenv('DB_URL')
assert url is not None, 'DB_URL environment variable needed.'
connectable = create_engine(url)
context.configure(
url=url,
target_metadata=target_metadata,
literal_binds=True,
dialect_opts={"paramstyle": "named"},
)
...
```
</details>

#### Create dockerfile (project root folder)
<details><summary>Dockerfile</summary>

```Dockerfile
FROM python:3.9-slim

RUN mkdir -p /orders/orders

WORKDIR /orders

# RUN pip install -U pip && pip install pipenv
RUN pip install --upgrade pip

# COPY Pipfile Pipfile.lock /orders/
COPY requirements.txt /orders/

# RUN pipenv install --system --deploy
RUN pip install -r requirements.txt

COPY orders/orders_service /orders/orders/orders_service/
COPY orders/repository /orders/orders/repository/
COPY orders/web /orders/orders/web/
COPY oas.yaml /orders/oas.yaml
COPY public_key.pem /orders/public_key.pem
COPY private_key.pem /orders/private.pem

EXPOSE 8000

CMD ["uvicorn", "orders.web.app:app", "--host", "0.0.0.0"]
```
</details>

#### Build Docker image
`$ docker build -t orders:1.0 .`

#### Run image
`$ docker run --env DB_URL=sqlite:///orders.db \
-v $(pwd)/orders.db:/orders/orders.db -p 8000:8000 -it orders:1.0`

Detached mode \
`$ docker run -d –-env DB_URL=sqlite:///orders.db \
-v $(pwd)/orders.db:/orders/orders.db -p 8000:8000 orders:1.0`

In detached mode container must be stopped using stop docker command
`$ docker stop <CONTAINER_ID>`
CONTAINER_ID will can be check using the docker command to list running containers
`$ docker ps`


## Run apps with Docker Compose

Docker compose allos to run multiple containers within a shared network

### A. Install docker compose using PIP
`pip install docker-compose`

**NOTE:** If pip installation fails download latest binary and follow instructions below.

### B. Install standalone docker compose 

Info: https://docs.docker.com/compose/install/standalone

`curl -SL https://github.com/docker/compose/releases/download/v2.23.3/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose`

#### Apply executable permissions to the standalone binary in the target path for the installation.
`chmod 777 /usr/local/bin/docker-compose`

#### Check installation
`$ docker-compose --version`

Output:
```bash
Docker Compose version v2.23.3
```


### Create docker-compose file for the orders service
<details><summary>docker-compose.yaml</summary>

```yaml
version: "3.9"

services:

  database:
    image: postgres:14.3
    ports:
      - 5432:5432
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_USER: postgres
      POSTGRES_DB: postgres
    volumes:
      - database-data:/var/lib/postgresql/data

  api:
    build: .
    ports:
      - 8000:8000
    depends_on:
      - database
    environment:
      DB_URL: postgresql://postgres:postgres@database:5432/postgres

volumes:
  database-data:
```
</details>

Check web API at : http://localhost:8000/docs/orders

**NOTE:** EndPoints should return error as far as postgre database has not created tables

#### Run migration to create tables in the database

```$ PYTHONPATH=`pwd` \
DB_URL=postgresql://postgres:postgres@localhost:5432/postgres alembic \
upgrade heads```

**NOTE:** If there is some error in migration check files under *migrations/versions*

Check web API at : http://localhost:8000/docs/orders

Now endpoints should work!!!

#### Create AWS Elastic Container Registry

If not already configured region has to be specified when running the command.

`aws ecr create-repository --repository-name coffeemesh-orders --region us-east-2`

<details><summary>Output</summary>

```json
{
  "repository": {
    "repositoryArn": "arn:aws:ecr:us-east-1e:<aws_account_id>:repository/coffeemesh-orders",
    "registryId": "876701361933",
    "repositoryName": "coffeemesh-orders",
    "repositoryUri": "<aws_account_id>.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders",
    "createdAt": "2021-11-16T10:08:42+00:00",
    "imageTagMutability": "MUTABLE",
    "imageScanningConfiguration": {
      "scanOnPush": false
    },
    "encryptionConfiguration": {
      "encryptionType": "AES256"
    }
  }
}
```
</details>

#### Tag the docker build
`$ docker tag orders:1.0 414116650220.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders:1.0`

#### Obtain login credentials (/home/<user>/.docker/config.json.)
`$ aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 414116650220.dkr.ecr.us-east-2.amazonaws.com`

#### Publish docker image to ECR
`$ docker push 414116650220.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders:1.0`

**Note:** If gettin `denied: Your authorization token has expired. Reauthenticate and try again.` message just repeat the previous step to get new credentials.


## Deploying microservice APIs with Kubernetes

#### Install eksctl (https://github.com/eksctl-io/eksctl)

```bash
ARCH=amd64
PLATFORM=$(uname -s)_$ARCH

curl -sLO "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_$PLATFORM.tar.gz"

# (Optional) Verify checksum
curl -sL "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_checksums.txt" | grep $PLATFORM | sha256sum --check

tar -xzf eksctl_$PLATFORM.tar.gz -C /tmp && rm eksctl_$PLATFORM.tar.gz

sudo mv /tmp/eksctl /usr/local/bin
```

### Create K8 cluster

Fargate is AWS’s serverless container service that allows us to run containers in the cloud without having to provision servers.

`$ eksctl create cluster --name coffeemesh --region us-east-2 --fargate --alb-ingress-access`
<details>

```bash
2023-12-18 17:43:26 [ℹ]  eksctl version 0.165.0
2023-12-18 17:43:26 [ℹ]  using region us-east-2
2023-12-18 17:43:27 [ℹ]  setting availability zones to [us-east-2c us-east-2a us-east-2b]
2023-12-18 17:43:27 [ℹ]  subnets for us-east-2c - public:192.168.0.0/19 private:192.168.96.0/19
2023-12-18 17:43:27 [ℹ]  subnets for us-east-2a - public:192.168.32.0/19 private:192.168.128.0/19
2023-12-18 17:43:27 [ℹ]  subnets for us-east-2b - public:192.168.64.0/19 private:192.168.160.0/19
2023-12-18 17:43:27 [ℹ]  using Kubernetes version 1.27
2023-12-18 17:43:27 [ℹ]  creating EKS cluster "coffeemesh" in "us-east-2" region with Fargate profile
2023-12-18 17:43:27 [ℹ]  if you encounter any issues, check CloudFormation console or try 'eksctl utils describe-stacks --region=us-east-2 --cluster=coffeemesh'
2023-12-18 17:43:27 [ℹ]  Kubernetes API endpoint access will use default of {publicAccess=true, privateAccess=false} for cluster "coffeemesh" in "us-east-2"
2023-12-18 17:43:27 [ℹ]  CloudWatch logging will not be enabled for cluster "coffeemesh" in "us-east-2"
2023-12-18 17:43:27 [ℹ]  you can enable it with 'eksctl utils update-cluster-logging --enable-types={SPECIFY-YOUR-LOG-TYPES-HERE (e.g. all)} --region=us-east-2 --cluster=coffeemesh'
2023-12-18 17:43:27 [ℹ]  
2 sequential tasks: { create cluster control plane "coffeemesh", 
    2 sequential sub-tasks: { 
        wait for control plane to become ready,
        create fargate profiles,
    } 
}
2023-12-18 17:43:27 [ℹ]  building cluster stack "eksctl-coffeemesh-cluster"
2023-12-18 17:43:28 [ℹ]  deploying stack "eksctl-coffeemesh-cluster"
2023-12-18 17:43:58 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:44:28 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:45:29 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:46:29 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:47:30 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:48:30 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:49:31 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:50:32 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:51:32 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:52:33 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-cluster"
2023-12-18 17:54:37 [ℹ]  creating Fargate profile "fp-default" on EKS cluster "coffeemesh"
2023-12-18 17:58:56 [ℹ]  created Fargate profile "fp-default" on EKS cluster "coffeemesh"
2023-12-18 17:59:27 [ℹ]  "coredns" is now schedulable onto Fargate
2023-12-18 18:00:32 [ℹ]  "coredns" is now scheduled onto Fargate
2023-12-18 18:00:32 [ℹ]  "coredns" pods are now scheduled onto Fargate
2023-12-18 18:00:32 [ℹ]  waiting for the control plane to become ready
2023-12-18 18:00:39 [✔]  saved kubeconfig as "/home/sabad/.kube/config"
2023-12-18 18:00:39 [ℹ]  no tasks
2023-12-18 18:00:39 [✔]  all EKS cluster resources for "coffeemesh" have been created
2023-12-18 18:00:50 [ℹ]  kubectl command should work with "/home/sabad/.kube/config", try 'kubectl get nodes'
2023-12-18 18:00:50 [✔]  EKS cluster "coffeemesh" in "us-east-2" region is ready
```
</details>

**NOTES:**
- Cluster info: `eksctl utils describe-stacks --region=us-east-2 --cluster=coffeemesh`
```2023-12-18 13:30:07 [!]  only 1 stacks found, for a ready-to-use cluster there should be at least 2``` (delete and create again)
- Clean up : `eksctl delete cluster --region=us-east-1e --name=coffeemesh`
- Web UI : CloudFormation control panel https://us-east-1.console.aws.amazon.com/ (notice the region used as prefix in the URL)

#### Point kubectl to the cluster

`$ aws eks update-kubeconfig --name coffeemesh --region  us-east-2`

#### Inspect properties
Get nodes :\
`$ kubectl get nodes`
```bash
NAME                                      STATUS   ROLES    AGE    VERSION
fargate-ip-192-168-109-159.ec2.internal   Ready    <none>   6h4m   v1.27.7-eks-4f4795d
fargate-ip-192-168-74-214.ec2.internal    Ready    <none>   6h4m   v1.27.7-eks-4f4795d
```

Get the list of pods running in the cluster: \
`$ kubectl get pods -A`

```bash
NAMESPACE     NAME                       READY   STATUS    RESTARTS   AGE
kube-system   coredns-788dbcccd5-kr7qd   1/1     Running   0          6h6m
kube-system   coredns-788dbcccd5-vgwtb   1/1     Running   0          6h6m
```

Kubernetes references:\
https://kubernetes.io/docs/reference/kubectl/
https://kubernetes.io/docs/reference/kubectl/cheatsheet/

### Using IAM roles for Kubernetes service accounts

To allow K8 cluster services to interact with AWS resources using the AWS API we need IAM roles entities.

Using OpenID Connect (OIDC) our pods can obtain temporary credentials to access the AWS API.

#### Check OIDC profider

`$ aws eks describe-cluster --name coffeemesh --region us-east-2 --query "cluster.identity.oidc.issuer" --output text`

output
```
https://oidc.eks.us-east-2.amazonaws.com/id/B9C20B17054CD4F43DF3500A2DC2A5D5
```
List all OIDC providers in AWS account: \
`$ aws iam list-open-id-connect-providers`
```json
{
    "OpenIDConnectProviderList": [
        {
            "Arn": "arn:aws:iam::414116650220:oidc-provider/oidc.eks.us-east-1e.amazonaws.com/id/B9C20B17054CD4F43DF3500A2DC2A5D5"
        }
    ]
}
```

Filter by ID using grep \
`$ aws iam list-open-id-connect-providers | grep B9C20B17054CD4F43DF3500A2DC2A5D5`

If the list is empty it means we need to create one: \
`$ eksctl utils associate-iam-oidc-provider --cluster coffeemesh --approve`

**NOTE:**
Check region in *aws configure* in case of error

```bash
Error: unable to describe cluster control plane: operation error EKS: DescribeCluster, https response error StatusCode: 404, RequestID: eb3006bf-297d-4958-9f84-43f894698a36, ResourceNotFoundException: No cluster found for name: coffeemesh.
```

If there are more than expected and want to remove some check in the web UI:
`https://us-east-1e.console.aws.amazon.com/iamv2/home?region=us-east-2#/identity_providers`


In case of Error Response as follows:
```bash
Error: could not create cluster provider from options: checking AWS STS access – cannot get role ARN for current session: operation error STS: GetCallerIdentity, https response error StatusCode: 0, RequestID: , request send failed, Post "https://sts..amazonaws.com/": dial tcp: lookup sts..amazonaws.com: no such host
```

- Check credentials in ~/.aws/credentials
- Run `aws configure`
- Fill info according to credentials and region:
  ```bash
  AWS Access Key ID [****************LKU4]: <aws_access_key_id>
  AWS Secret Access Key [****************MitT]: <aws_secret_access_key>
  Default region name [None]: us-east-2
  Default output format [None]:
  ```

Expected output sample:
```bash
eksctl utils associate-iam-oidc-provider --cluster coffeemesh --approve
2023-12-06 18:00:36 [ℹ]  will create IAM Open ID Connect provider for cluster "coffeemesh" in "us-east-1e"
2023-12-06 18:00:37 [✔]  created IAM Open ID Connect provider for cluster "coffeemesh" in "us-east-1e"
```
## Deploying a Kubernetes load balancer

The cluster is not accessible from outside of the VPC by default.

To enable external access create an AWS Application Load Balancer (ALB) that accepts traffic from the outside and forwards it to the ingress controller.

ALB forward traffic to target groups based on rules (for example IPs, IDs).

It also monitors registered targets' health and ony redirected to healthy ones.

#### Download iam_policy sample:
`$ curl -o alb_controller_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json`

#### Create IAM policy :
`$ aws iam create-policy --policy-name ALBControllerPolicy --policy-document file://alb_controller_policy.json`
<details><summary>Output</summary>

```json
{
    "Policy": {
        "PolicyName": "ALBControllerPolicy",
        "PolicyId": "ANPAWA22GTTWF6HH3LRTW",
        "Arn": "arn:aws:iam::414116650220:policy/ALBControllerPolicy",
        "Path": "/",
        "DefaultVersionId": "v1",
        "AttachmentCount": 0,
        "PermissionsBoundaryUsageCount": 0,
        "IsAttachable": true,
        "CreateDate": "2023-12-06T17:22:34Z",
        "UpdateDate": "2023-12-06T17:22:34Z"
    }
}
```
</details>
</br>

#### Create IAM role associated to K8 service account for the load balancer:

account_id  = 414116650220

```bash
$ eksctl create iamserviceaccount \
--cluster=coffeemesh \
--namespace=kube-system \
--name=alb-controller \
--attach-policy-arn=arn:aws:iam::414116650220:policy/ALBControllerPolicy \
--override-existing-serviceaccounts \
--approve
```


<details><summary>Output</summary>

```bash
2023-12-06 18:23:51 [ℹ]  1 iamserviceaccount (kube-system/alb-controller) was included (based on the include/exclude rules)
2023-12-06 18:23:51 [!]  metadata of serviceaccounts that exist in Kubernetes will be updated, as --override-existing-serviceaccounts was set
2023-12-06 18:23:51 [ℹ]  1 task: { 
    2 sequential sub-tasks: { 
        create IAM role for serviceaccount "kube-system/alb-controller",
        create serviceaccount "kube-system/alb-controller",
    } }2023-12-06 18:23:51 [ℹ]  building iamserviceaccount stack "eksctl-coffeemesh-addon-iamserviceaccount-kube-system-alb-controller"
2023-12-06 18:23:51 [ℹ]  deploying stack "eksctl-coffeemesh-addon-iamserviceaccount-kube-system-alb-controller"
2023-12-06 18:23:51 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-addon-iamserviceaccount-kube-system-alb-controller"
2023-12-06 18:24:22 [ℹ]  waiting for CloudFormation stack "eksctl-coffeemesh-addon-iamserviceaccount-kube-system-alb-controller"
2023-12-06 18:24:23 [ℹ]  created serviceaccount "kube-system/alb-controller"
```
</details>
</br>


#### Use Helm to to install the controller
- Download installer \
`curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 -o helm_installer`

- Run installer \
`$ . helm_installer`

- Install the controller
`eksctl get cluster --name coffeemesh -o json | jq '.[0].ResourcesVpcConfig.VpcId'`

  output
  ```
  "eks" has been added to your repositories
  ```

- Update Helm
`helm repo update`

- Get VPC ID
```eksctl get cluster --name coffeemesh -o json | jq '.[0].ResourcesVpcConfig.VpcId'```
output
```
"vpc-0ea4a9acc255ff570"
```

#### Install AWS Load Balancer Controller
  ```bash
  $ helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=coffeemesh \
  --set serviceAccount.create=false \
  --set serviceAccount.name=alb-controller \
  --set vpcId=vpc-0ea4a9acc255ff570
  ```
  output:
  ```bash
    NAME: aws-load-balancer-controller
    LAST DEPLOYED: Wed Dec  6 19:00:23 2023
    NAMESPACE: kube-system
    STATUS: deployed
    REVISION: 1
    TEST SUITE: None
    NOTES:
    AWS Load Balancer controller installed!
  ```
#### Verify deployment
`kubectl get deployment -n kube-system aws-load-balancer-controller`

```bash
NAME                           READY   UP-TO-DATE   AVAILABLE   AGE
aws-load-balancer-controller   2/2     2            2           3m13s
```

### Deploying microservices to the Kubernetes cluster
#### Deploy service to a new namespace
`kubectl create namespace orders-service`

Output: \
```namespace/orders-service created```

#### Create fargateprofile to run pods on AWS servers
`$ eksctl create fargateprofile --namespace orders-service --cluster coffeemesh --region us-east-2`

output
```bash
2023-12-06 21:00:02 [ℹ]  creating Fargate profile "fp-a22a48d1" on EKS cluster "coffeemesh"
2023-12-06 21:02:13 [ℹ]  created Fargate profile "fp-a22a48d1" on EKS cluster "coffeemesh"
```

### Creating a deployment object
#### Declare a deploymen manifest
<details><summary>orders-service-deployment.yaml</summary>

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-service
  namespace: orders-service
  labels:
    app: orders-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: orders-service
  template:
    metadata:
      labels:
        app: orders-service
    spec:
      containers:
        - name: orders-service
          image: 414116650220.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders:1.0
          ports:
            - containerPort: 8000
          imagePullPolicy: Always
```
</details>


#### Create deployment
`kubectl apply -f orders-service-deployment.yaml`

output
```
deployment.apps/orders-service created
```

#### Check status
`kubectl get pods -n orders-service`

ImagePullBAckOff (could be cause when trying to pull an unexistant image from the repository)
```bash
NAME                              READY   STATUS             RESTARTS   AGE
orders-service-7bf8d6b9b6-pmhpd   0/1     ImagePullBackOff   0          115s
```
In this case check image repository and upload the missing images.

#### Collect info

`kubectl describe pod -n orders-service`

<details>

```bash
Name:                 orders-service-7bf8d6b9b6-pmhpd
Namespace:            orders-service
Priority:             2000001000
Priority Class Name:  system-node-critical
Service Account:      default
Node:                 fargate-ip-192-168-89-122.ec2.internal/192.168.89.122
Start Time:           Wed, 06 Dec 2023 21:11:55 +0100
Labels:               app=orders-service
                      eks.amazonaws.com/fargate-profile=fp-a22a48d1
                      pod-template-hash=7bf8d6b9b6
Annotations:          CapacityProvisioned: 0.25vCPU 0.5GB
                      Logging: LoggingDisabled: LOGGING_CONFIGMAP_NOT_FOUND
Status:               Pending
IP:                   192.168.89.122
IPs:
  IP:           192.168.89.122
Controlled By:  ReplicaSet/orders-service-7bf8d6b9b6
Containers:
  orders-service:
    Container ID:   
    Image:          414116650220.dkr.ecr.us-east-1e.amazonaws.com/coffeemesh-orders:1.0
    Image ID:       
    Port:           8000/TCP
    Host Port:      0/TCP
    State:          Waiting
      Reason:       ImagePullBackOff
    Ready:          False
    Restart Count:  0
    Environment:    <none>
    Mounts:
      /var/run/secrets/kubernetes.io/serviceaccount from kube-api-access-grlw4 (ro)
Conditions:
  Type              Status
  Initialized       True 
  Ready             False 
  ContainersReady   False 
  PodScheduled      True 
Volumes:
  kube-api-access-grlw4:
    Type:                    Projected (a volume that contains injected data from multiple sources)
    TokenExpirationSeconds:  3607
    ConfigMapName:           kube-root-ca.crt
    ConfigMapOptional:       <nil>
    DownwardAPI:             true
QoS Class:                   BestEffort
Node-Selectors:              <none>
Tolerations:                 node.kubernetes.io/not-ready:NoExecute op=Exists for 300s
                             node.kubernetes.io/unreachable:NoExecute op=Exists for 300s
Events:
  Type     Reason           Age                   From               Message
  ----     ------           ----                  ----               -------
  Warning  LoggingDisabled  11m                   fargate-scheduler  Disabled logging because aws-logging configmap was not found. configmap "aws-logging" not found
  Normal   Scheduled        10m                   fargate-scheduler  Successfully assigned orders-service/orders-service-7bf8d6b9b6-pmhpd to fargate-ip-192-168-89-122.ec2.internal
  Normal   Pulling          8m38s (x4 over 10m)   kubelet            Pulling image "414116650220.dkr.ecr.us-east-1e.amazonaws.com/coffeemesh-orders:1.0"
  Warning  Failed           8m38s (x4 over 10m)   kubelet            Failed to pull image "414116650220.dkr.ecr.us-east-1e.amazonaws.com/coffeemesh-orders:1.0": rpc error: code = NotFound desc = failed to pull and unpack image "414116650220.dkr.ecr.us-east-1e.amazonaws.com/coffeemesh-orders:1.0": failed to resolve reference "414116650220.dkr.ecr.us-east-1e.amazonaws.com/coffeemesh-orders:1.0": 414116650220.dkr.ecr.e.amazonaws.com/coffeemesh-orders:1.0: not found  
  Warning  Failed           8m38s (x4 over 10m)   kubelet            Error: ErrImagePull
  Warning  Failed           8m15s (x6 over 10m)   kubelet            Error: ImagePullBackOff
  Normal   BackOff          4m51s (x21 over 10m)  kubelet            Back-off pulling image "414116650220.dkr.ecr.us-east-1e.amazonaws.com/coffeemesh-orders:1.0"
```
</details>

Expected output (`kubectl get pods -n orders-service`)

```bash
NAME                              READY   STATUS    RESTARTS   AGE
orders-service-7bf8d6b9b6-pmhpd   1/1     Running   0          13m
```

### Creating a service object

Services are K8 objects that allow us to exposer pods as networking services.

#### Create orders-service.yaml

<details>

```yaml
apiVersion: v1
kind: Service
metadata:
  name: orders-service
  namespace: orders-service
  labels:
    app: orders-service
spec:
  selector:
    app: orders-service
  type: ClusterIP
  ports:
    - protocol: http
      port: 80
      targetPort: 8000
```
</details>

#### Deploy service

`kubectl apply -f orders-service.yaml`

Expected output
```
service/orders-service created
```

Error
```
Error from server (InternalError): error when creating "orders-service.yaml": Internal error occurred: failed calling webhook "mservice.elbv2.k8s.aws": failed to call webhook: Post "https://aws-load-balancer-webhook-service.kube-system.svc:443/mutate-v1-service?timeout=10s": no endpoints available for service "aws-load-balancer-webhook-service"
```

#### Exposing services with ingress objects
<details><summary></summary>

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: orders-service-ingress
  namespace: orders-service
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/scheme: internet-facing
spec:
  rules:
  - http:
      paths:
      - path: /orders
        pathType: Prefix
        backend:
          service:
            name: orders-service
            port:
              number: 80
      - path: /docs/orders
        pathType: Prefix
        backend:
          service:
            name: orders-service
            port:
              number: 80
      - path: /openapi/orders.json
        pathType: Prefix
        backend:
          service:
            name: orders-service
            port:
              number: 80
```
</details>


#### Create ingress resource

`kubectl apply -f orders-service-ingress.yaml`

output
```bash
Warning: annotation "kubernetes.io/ingress.class" is deprecated, please use 'spec.ingressClassName' instead
ingress.networking.k8s.io/orders-service-ingress created
```
NOTES:
If error check service availability:
`kubectl get svc -n kube-system aws-load-balancer-webhook-service`
```bash
NAME                                TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)   AGE
aws-load-balancer-webhook-service   ClusterIP   10.100.127.129   <none>        443/TCP   29m
```
Check Pod logs
`kubectl get pods -n orders-service`
```bash
NAME                              READY   STATUS    RESTARTS   AGE
orders-service-b488964d9-r2sgx   1/1     Running   0          20m
```
`kubectl logs -n kube-system orders-service-b488964d9-r2sgx`

**NOTE:** Error expected if logs are disabled

#### Find endpoint to ingress rule
`kubectl get ingress/orders-service-ingress -n orders-service`

```bash
AME                     CLASS    HOSTS   ADDRESS                                                                   PORTS   AGE
orders-service-ingress   <none>   *       k8s-ordersse-ordersse-3c39119336-1620345271.us-east-2.elb.amazonaws.com   80      82s
```

ADDRESS field is the URL of the load balancer \
`k8s-ordersse-ordersse-3c39119336-1620345271.us-east-2.elb.amazonaws.com`

#### Command to get value

`kubectl get ingress/orders-service-ingress -n orders-service -o json | jq '.status.loadBalancer.ingress[0].hostname'`

output
"k8s-ordersse-ordersse-3c39119336-1875658907.us-east-1e.elb.amazonaws.com"

Check access to API documentation
`curl http://k8s-ordersse-ordersse-3c39119336-1620345271.us-east-2.elb.amazonaws.com/openapi/orders.json`


### Creating an Aurora Serverless database
Choose/create VPC for the database
- Aurora Serverlesss only supports one subnet per availabitity zone.
- When creating a database subnet group, subnets must all be private or public.

#### List private subnets in the VPC to obtain the ID of the K8 cluster's VPC
`$ eksctl get cluster --name coffeemesh -o json | jq '.[0].ResourcesVpcConfig.VpcId'`

Output:
```bash
"vpc-0ea4a9acc255ff570"
```

#### Get the IDs of the private subnets in the VPC
`$ aws ec2 describe-subnets --filters Name=vpc-id,Values=vpc-0ea4a9acc255ff570 --output json | jq '.Subnets[] | select(.MapPublicIpOnLaunch == false) | .SubnetId'`

Output:
```bash
"subnet-01b4ab1aac8e4d2d6"
"subnet-03f96515839b82116"
"subnet-036163729699d4b20"
```

#### Create database subnet group
`$ aws rds create-db-subnet-group --db-subnet-group-name coffeemesh-db-subnet-group --db-subnet-group-description "Private subnets" --subnet-ids "subnet-01b4ab1aac8e4d2d6" "subnet-03f96515839b82116" "subnet-036163729699d4b20"`

<details><summary>Output:</summary>

```json
{
    "DBSubnetGroup": {
        "DBSubnetGroupName": "coffeemesh-db-subnet-group",
        "DBSubnetGroupDescription": "Private subnets",
        "VpcId": "vpc-0ea4a9acc255ff570",
        "SubnetGroupStatus": "Complete",
        "Subnets": [
            {
                "SubnetIdentifier": "subnet-036163729699d4b20",
                "SubnetAvailabilityZone": {
                    "Name": "us-east-2c"
                },
                "SubnetOutpost": {},
                "SubnetStatus": "Active"
            },
            {
                "SubnetIdentifier": "subnet-03f96515839b82116",
                "SubnetAvailabilityZone": {
                    "Name": "us-east-2a"
                },
                "SubnetOutpost": {},
                "SubnetStatus": "Active"
            },
            {
                "SubnetIdentifier": "subnet-01b4ab1aac8e4d2d6",
                "SubnetAvailabilityZone": {
                    "Name": "us-east-2b"
                },
                "SubnetOutpost": {},
                "SubnetStatus": "Active"
            }
        ],
        "DBSubnetGroupArn": "arn:aws:rds:us-east-2:414116650220:subgrp:coffeemesh-db-subnet-group",
        "SupportedNetworkTypes": [
            "IPV4"
        ]
    }
}
```
</details>

#### Create security group to define what in/out traffic is allowed from the VPC
`$ aws ec2 create-security-group --group-name db-access --vpc-id vpc-0ea4a9acc255ff570 --description "Security group for db access"`

Output:
```json
{
    "GroupId": "sg-0f8ace12fef82e7ee"
}
```

#### Create inbound traffic rule for db access security group
`$ aws ec2 authorize-security-group-ingress --group-id sg-0f8ace12fef82e7ee --ip-permissions '[{"FromPort":5432,"ToPort":5432,"IpProtocol":"TCP","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]'`

**NOTE:** Notice the IpRange is not restricted because working in a private subnet, but it is recommendable to restrict the range to the ones used by the pods.

<details><summary>Output:</summary>

```
{
    "Return": true,
    "SecurityGroupRules": [
        {
            "SecurityGroupRuleId": "sgr-09afb38eef93a9800",
            "GroupId": "sg-0f8ace12fef82e7ee",
            "GroupOwnerId": "414116650220",
            "IsEgress": false,
            "IpProtocol": "tcp",
            "FromPort": 5432,
            "ToPort": 5432,
            "CidrIpv4": "0.0.0.0/0"
        }
    ]
}
```
</details>

#### Launch an Aurora Serverless cluster:

`$ aws rds create-db-cluster --db-cluster-identifier coffeemesh-orders-db --engine aurora-postgresql --engine-version 11.16 --engine-mode serverless --scaling-configuration MinCapacity=8,MaxCapacity=64,SecondsUntilAutoPause=1000,AutoPause=true --master-username sabad --master-user-password S@mpleP@ss951753 --vpc-security-group-ids sg-0f8ace12fef82e7ee --db-subnet-group coffeemesh-db-subnet-group`

<details>

```json
{
  "DBCluster": {
      "AllocatedStorage": 1,
      "AvailabilityZones": [
          "us-east-2b",
          "us-east-2c",
          "us-east-2a"
      ],
      "BackupRetentionPeriod": 1,
      "DBClusterIdentifier": "coffeemesh-orders-db",
      "DBClusterParameterGroup": "default.aurora-postgresql11",
      "DBSubnetGroup": "coffeemesh-db-subnet-group",
      "Status": "creating",
      "Endpoint": "coffeemesh-orders-db.cluster-ce7qi4k09cj1.us-east-2.rds.amazonaws.com",
      "ReaderEndpoint": "coffeemesh-orders-db.cluster-ro-ce7qi4k09cj1.us-east-2.rds.amazonaws.com",
      "MultiAZ": false,
      "Engine": "aurora-postgresql",
      "EngineVersion": "11.21",
      "Port": 5432,
      "MasterUsername": "sabad",
      "PreferredBackupWindow": "03:17-03:47",
      "PreferredMaintenanceWindow": "wed:06:38-wed:07:08",
      "ReadReplicaIdentifiers": [],
      "DBClusterMembers": [],
      "VpcSecurityGroups": [
          {
              "VpcSecurityGroupId": "sg-0f8ace12fef82e7ee",
              "Status": "active"
          }
      ],
      "HostedZoneId": "Z2XHWR1WZ565X2",
      "StorageEncrypted": true,
      "KmsKeyId": "arn:aws:kms:us-east-2:414116650220:key/cc4dae5f-c438-487c-8841-c802ebabaa67",
      "DbClusterResourceId": "cluster-DM4FBTE3ENFBBJ273YHPGNFBQA",
      "DBClusterArn": "arn:aws:rds:us-east-2:414116650220:cluster:coffeemesh-orders-db",
      "AssociatedRoles": [],
      "IAMDatabaseAuthenticationEnabled": false,
      "ClusterCreateTime": "2023-12-18T18:47:48.660Z",
      "EngineMode": "serverless",
      "DeletionProtection": false,
      "HttpEndpointEnabled": false,
      "CopyTagsToSnapshot": false,
      "CrossAccountClone": false,
      "DomainMemberships": [],
      "TagList": [],
      "AutoMinorVersionUpgrade": true,
      "NetworkType": "IPV4"
  }
}
```
</details>

### Managing secrets in Kubernetes
The native way to manage sensitive information in Kubernetes is using
Kubernetes secrets.

AWS EKS offers two secure ways to manage K8 secrets:
- AWS Key Management Service (KMS)
- AWS Secrets & Configuration PRovoder for K8

### Using envelope encryption

Envelope encryption encrypts data with a data encryption key (DEK) and encrypts the DEK with a key encryption key (KEK)

#### Generate AWS KMS Key
`$ aws kms create-key`
```json
{
    "KeyMetadata": {
        "AWSAccountId": "414116650220",
        "KeyId": "e5df813d-108e-48f1-9592-6ac04a9a2997",
        "Arn": "arn:aws:kms:us-east-2:414116650220:key/e5df813d-108e-48f1-9592-6ac04a9a2997",
        "CreationDate": 1702927863.543,
        "Enabled": true,
        "Description": "",
        "KeyUsage": "ENCRYPT_DECRYPT",
        "KeyState": "Enabled",
        "Origin": "AWS_KMS",
        "KeyManager": "CUSTOMER",
        "CustomerMasterKeySpec": "SYMMETRIC_DEFAULT",
        "KeySpec": "SYMMETRIC_DEFAULT",
        "EncryptionAlgorithms": [
            "SYMMETRIC_DEFAULT"
        ],
        "MultiRegion": false
    }
}
``` 
#### Enable secrets encryption in K8 cluster using elkctl
`$ eksctl utils enable-secrets-encryption --cluster coffeemesh --key-arn=arn:aws:kms:us-east-2:414116650220:key/e5df813d-108e-48f1-9592-6ac04a9a2997 --region us-east-2`
<details>

```bash
2023-12-18 20:33:03 [ℹ]  initiated KMS encryption, this may take up to 45 minutes to complete
2023-12-18 20:49:40 [ℹ]  KMS encryption successfully enabled on cluster "coffeemesh"
2023-12-18 20:49:40 [ℹ]  updating all Secret resources to apply KMS encryption
2023-12-18 20:49:41 [ℹ]  KMS encryption applied to all Secret resources
```
</details>

#### Define database connection string (to be used later)
`postgresql://username:password@localhost:5432/postgres`
`postgresql://sabad:S*mpleP*ass742@localhost:5432/postgres`

#### Store the database connection string as a Kubernetes secret
`$ kubectl create secret generic -n orders-service db-credentials --from-literal=DB_URL=<connection_string>`
`$ kubectl create secret generic -n orders-service db-credentials --from-literal=DB_URL=postgresql://sabad:S*mpleP*ass742@localhost:5432/postgres`

Output: `secret/db-credentials created`

#### Get the details of the created secret object
`$ kubectl get secret db-credentials -n orders-service -o json`

```json
{
    "apiVersion": "v1",
    "data": {
        "DB_URL": "cG9zdGdyZXNxbDovL3NhYmFkOlMqbXBsZVAqYXNzNzQyQGxvY2FsaG9zdDo1NDMyL3Bvc3RncmVz"
    },
    "kind": "Secret",
    "metadata": {
        "creationTimestamp": "2023-12-18T19:50:34Z",
        "name": "db-credentials",
        "namespace": "orders-service",
        "resourceVersion": "45480",
        "uid": "7a19457a-ed6e-4827-bb3d-10809ad297b0"
    },
    "type": "Opaque"
}
```

#### To Obtain encoded values run:
`$ echo cG9zdGdyZXNxbDovL3NhYmFkOlMqbXBsZVAqYXNzNzQyQGxvY2FsaG9zdDo1NDMyL3Bvc3RncmVz | base64 --decode`

Output: `postgresql://sabad:S*mpleP*ass742@localhost:5432/postgres`

#### Update the order service deployment to consume the secret and expose it as an environment variable
<details><summary>orders-service-deployment.yaml</summary>

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-service
  namespace: orders-service
  labels:
    app: orders-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: orders-service
  template:
    metadata:
      labels:
        app: orders-service
    spec:
      containers:
        - name: orders-service
          image: 414116650220.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders:1.0
          ports:
            - containerPort: 8000
          imagePullPolicy: Always
          envFrom:
            - secretRef:
                name: db-credentials
```
</details>

#### Apply changes: `kubectl apply -f orders-service-deployment.yaml`

**Yaml format error:** `The request is invalid: patch: Invalid value:...`
Surely added values are not nested correctly. Check provided sample.

**Expected Output:** `deployment.apps/orders-service configured`

Running the database migrations and connecting our service
to the database


## Running the database migrations and connecting our service to the database

Database can not be access directly to run migrations.

There are two main options:
- Connect through a bastion server. It allows to establish a secure connection with a private net.
- Create a K8 job

To create a K8 job we need to create a Docker image for running the database migrations.

<details><summary>migratinos.dockerfile</summary>

```dockerfile
FROM python:3.9-slim
RUN mkdir -p /orders/orders
WORKDIR /orders
RUN pip install -U pip && pip install pipenv
COPY requirements.txt /orders/
RUN pip install -r requirements.txt
COPY orders/repository /orders/orders/repository/
COPY migrations /orders/migrations
COPY alembic.ini /orders/alembic.ini
ENV PYTHONPATH=/orders
CMD ["alembic", "upgrade", "heads"]
```
</details>

**Additional steps:** \
- Update *requirements.txt* : `pip freeze > requirements.txt`
- Comment # urllib3==2.0.7 as it caused conflicts previously.

#### Build docker image
`$ docker build -t <aws_account_number>.dkr.ecr.<aws_region>.amazonaws.com/coffeemesh-orders-migrations:1.0 -f migrations.dockerfile .`
`$ docker build -t 414116650220.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders-migrations:1.0 -f migrations.dockerfile .`
          
#### Create repository
`$ aws ecr create-repository --repository-name coffeemesh-orders-migrations`
<details>

```json
{
    "repository": {
        "repositoryArn": "arn:aws:ecr:us-east-2:414116650220:repository/coffeemesh-orders-migrations",
        "registryId": "414116650220",
        "repositoryName": "coffeemesh-orders-migrations",
        "repositoryUri": "414116650220.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders-migrations",
        "createdAt": 1702930370.0,
        "imageTagMutability": "MUTABLE",
        "imageScanningConfiguration": {
            "scanOnPush": false
        },
        "encryptionConfiguration": {
            "encryptionType": "AES256"
        }
    }
}
```
</details>

#### Push image
`$ docker push 414116650220.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders-migrations:1.0`

#### Create K8 job object via manifest file
<details><summary>orders-migrations-job.yaml</summary>

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: orders-service-migrations
  namespace: orders-service
  labels:
    app: orders-service
spec:
  ttlSecondsAfterFinished: 30
  template:
    spec:
      containers:
        - name: orders-service-migrations
          image: 414116650220.dkr.ecr.us-east-2.amazonaws.com/coffeemesh-orders-migrations:1.0
          imagePullPolicy: Always
          envFrom:
            - secretRef:
                name: db-credentials
      restartPolicy: Never
```
</details>


#### Create job:
`$ kubectl apply -f orders-migrations-job.yaml`

Output: `job.batch/orders-service-migrations created`

#### Check pod status
`kubectl get pods -n orders-service`

```bash
NAME                              READY   STATUS    RESTARTS   AGE
orders-service-76f5666675-zfc66   1/1     Running   0          27m
orders-service-migrations-mwgsj   0/1     Pending   0          36s
```

#### Logs (if activated)
`$ kubectl logs -f jobs/orders-service-migrations -n orders-service`