# Custom Cartography image with AWS CLI for EKS authentication.
# The official image lacks 'aws' binary required for: aws eks get-token
# FROM ghcr.io/cartography-cncf/cartography:latest
FROM ghcr.io/cartography-cncf/cartography:0.134

USER root

# PyYAML for kubeconfig filtering script (may not be in base)
RUN python3 -m pip install --no-cache-dir pyyaml

# Install AWS CLI v2 (required for EKS exec auth: aws eks get-token)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    groff \
    ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && AWSCLI_ZIP=$( [ "$ARCH" = "arm64" ] && echo "awscli-exe-linux-aarch64.zip" || echo "awscli-exe-linux-x86_64.zip" ) \
    && curl -sS "https://awscli.amazonaws.com/${AWSCLI_ZIP}" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws /var/lib/apt/lists/*

# Copy entrypoint that optionally filters kubeconfig to a single context
COPY cartography-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/cartography-entrypoint.sh

# Patch eks.py: skip aws-auth ConfigMap when 404 (EKS Access Entries API-only clusters)
COPY patches/apply-eks-patch.py /tmp/
RUN python3 /tmp/apply-eks-patch.py && rm /tmp/apply-eks-patch.py

# EC2SecurityGroupInstanceSchema: add `name` (alias GroupId) for QueryBuilder / analysis jobs
COPY patches/apply-securitygroup-name-patch.py /tmp/
RUN python3 /tmp/apply-securitygroup-name-patch.py && rm /tmp/apply-securitygroup-name-patch.py

USER 10001

ENTRYPOINT ["/usr/local/bin/cartography-entrypoint.sh"]
