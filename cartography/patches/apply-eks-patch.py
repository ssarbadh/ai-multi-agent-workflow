#!/usr/bin/env python3
"""
Patch Cartography eks.py to handle EKS clusters using Access Entries API only
(no aws-auth ConfigMap). When aws-auth returns 404, skip and continue to Access Entries.
"""
import sys

EKS_PY = "/var/cartography/.local/share/uv/tools/cartography/lib/python3.10/site-packages/cartography/intel/kubernetes/eks.py"

# Exact block from Cartography (4-space indent)
OLD = '''    # 1. Sync AWS IAM mappings (aws-auth ConfigMap)
    logger.info("Syncing AWS IAM mappings from aws-auth ConfigMap")
    configmap = get_aws_auth_configmap(k8s_client)
    auth_mappings = parse_aws_auth_map(configmap)

    # Transform and load both role and user mappings
    if auth_mappings.get("roles") or auth_mappings.get("users"):
        transformed_data = transform_aws_auth_mappings(auth_mappings, cluster_name)
        load_aws_auth_mappings(
            neo4j_session,
            transformed_data["users"],
            transformed_data["groups"],
            update_tag,
            cluster_id,
            cluster_name,
        )
        logger.info(
            f"Successfully synced {len(auth_mappings.get('roles', []))} AWS IAM role mappings "
            f"and {len(auth_mappings.get('users', []))} AWS IAM user mappings"
        )
    else:
        logger.info("No role or user mappings found in aws-auth ConfigMap")

    # 2. Sync EKS Access Entries (EKS API)'''

NEW = '''    # 1. Sync AWS IAM mappings (aws-auth ConfigMap)
    try:
        logger.info("Syncing AWS IAM mappings from aws-auth ConfigMap")
        configmap = get_aws_auth_configmap(k8s_client)
        auth_mappings = parse_aws_auth_map(configmap)

        # Transform and load both role and user mappings
        if auth_mappings.get("roles") or auth_mappings.get("users"):
            transformed_data = transform_aws_auth_mappings(auth_mappings, cluster_name)
            load_aws_auth_mappings(
                neo4j_session,
                transformed_data["users"],
                transformed_data["groups"],
                update_tag,
                cluster_id,
                cluster_name,
            )
            logger.info(
                f"Successfully synced {len(auth_mappings.get('roles', []))} AWS IAM role mappings "
                f"and {len(auth_mappings.get('users', []))} AWS IAM user mappings"
            )
        else:
            logger.info("No role or user mappings found in aws-auth ConfigMap")
    except ApiException as e:
        if e.status == 404:
            logger.info(
                "aws-auth ConfigMap not found (cluster likely uses EKS Access Entries API only); "
                "skipping ConfigMap sync, will use Access Entries"
            )
        else:
            raise

    # 2. Sync EKS Access Entries (EKS API)'''


def main():
    with open(EKS_PY, "r") as f:
        content = f.read()

    if "except ApiException as e:" in content and "aws-auth ConfigMap not found" in content:
        print("Patch already applied", file=sys.stderr)
        return 0

    if "from kubernetes.client.exceptions import ApiException" not in content:
        content = content.replace(
            "import yaml\n",
            "import yaml\nfrom kubernetes.client.exceptions import ApiException\n",
        )

    if OLD not in content:
        print("Could not find block to replace. eks.py may have changed.", file=sys.stderr)
        return 1

    content = content.replace(OLD, NEW)

    with open(EKS_PY, "w") as f:
        f.write(content)

    print("Applied EKS aws-auth optional patch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
