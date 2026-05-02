"""Kubernetes client."""

import logging
from typing import Dict, Any, Optional
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from app.core.config import settings

logger = logging.getLogger(__name__)


class KubernetesClient:
    """Client for Kubernetes operations."""
    
    def __init__(self):
        self.config_path = settings.K8S_CONFIG_PATH
        self.context = settings.K8S_CONTEXT
        
        # Initialize clients
        self.core_v1 = None
        self.apps_v1 = None
        self.batch_v1 = None
        
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize Kubernetes clients."""
        try:
            # Load kubeconfig
            config.load_kube_config(
                config_file=self.config_path,
                context=self.context
            )
            
            # Initialize API clients
            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.batch_v1 = client.BatchV1Api()
            
            logger.info(f"Kubernetes clients initialized for context: {self.context}")
            
        except Exception as e:
            logger.warning(f"Failed to initialize Kubernetes clients: {e}")
    
    async def create_deployment(
        self,
        name: str,
        namespace: str,
        image: str,
        replicas: int = 1,
        labels: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Create a Kubernetes deployment.
        
        Args:
            name: Deployment name
            namespace: Namespace
            image: Container image
            replicas: Number of replicas
            labels: Labels
            
        Returns:
            Deployment details
        """
        try:
            # Create deployment spec
            deployment = client.V1Deployment(
                api_version="apps/v1",
                kind="Deployment",
                metadata=client.V1ObjectMeta(name=name, labels=labels or {}),
                spec=client.V1DeploymentSpec(
                    replicas=replicas,
                    selector=client.V1LabelSelector(
                        match_labels=labels or {"app": name}
                    ),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(labels=labels or {"app": name}),
                        spec=client.V1PodSpec(
                            containers=[
                                client.V1Container(
                                    name=name,
                                    image=image
                                )
                            ]
                        )
                    )
                )
            )
            
            # Create deployment
            response = self.apps_v1.create_namespaced_deployment(
                namespace=namespace,
                body=deployment
            )
            
            logger.info(f"Created deployment: {name} in namespace: {namespace}")
            
            return {
                "name": response.metadata.name,
                "namespace": response.metadata.namespace,
                "replicas": response.spec.replicas,
                "status": "created"
            }
            
        except ApiException as e:
            logger.error(f"Failed to create deployment: {e}")
            raise
    
    async def list_pods(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None
    ) -> list:
        """List pods in namespace."""
        try:
            response = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector
            )
            
            pods = []
            for pod in response.items:
                pods.append({
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "status": pod.status.phase,
                    "ip": pod.status.pod_ip
                })
            
            return pods
            
        except ApiException as e:
            logger.error(f"Failed to list pods: {e}")
            raise


# Global instance
k8s_client = KubernetesClient()
