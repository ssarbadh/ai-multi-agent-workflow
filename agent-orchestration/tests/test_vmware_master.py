"""
VMware Integration Master Test Suite.

Comprehensive tests for VMware vCenter integration covering:
- Connection and authentication
- Inventory discovery (read-only)
- Datacenter, Cluster, Host operations
- Virtual Machine queries
- Datastore and Network listing
- Dependency discovery
- Health checks

Per HLD Testing Requirements:
- Unit: schema validation, client methods
- Integration: end-to-end discovery operations
- All operations are READ-ONLY (no destructive tests)
"""

import pytest
from datetime import datetime, timezone
from typing import Dict, Any, List

# Test configuration
VMWARE_HOST = "192.168.10.5"
VMWARE_USERNAME = "vmware_agent@vsphere.local"
VMWARE_PASSWORD = "NexTurn@2025"


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def vmware_client():
    """Create VMware client for testing."""
    from app.clients.vmware_client import VMwareClient
    return VMwareClient(
        host=VMWARE_HOST,
        username=VMWARE_USERNAME,
        password=VMWARE_PASSWORD,
        port=443,
        verify_ssl=False
    )


@pytest.fixture
def vmware_service():
    """Create VMware service for testing."""
    from app.services.vmware_service import VMwareService
    from app.clients.vmware_client import VMwareClient
    
    client = VMwareClient(
        host=VMWARE_HOST,
        username=VMWARE_USERNAME,
        password=VMWARE_PASSWORD,
        port=443,
        verify_ssl=False
    )
    return VMwareService(client=client)


# =============================================================================
# SCHEMA VALIDATION TESTS
# =============================================================================

class TestSchemaValidation:
    """Test Pydantic schema validation."""
    
    def test_power_state_enum(self):
        """Test power state enum values."""
        from app.schemas.vmware_schemas import PowerState
        
        assert PowerState.POWERED_ON.value == "poweredOn"
        assert PowerState.POWERED_OFF.value == "poweredOff"
        assert PowerState.SUSPENDED.value == "suspended"
    
    def test_connection_state_enum(self):
        """Test connection state enum values."""
        from app.schemas.vmware_schemas import ConnectionState
        
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.DISCONNECTED.value == "disconnected"
    
    def test_virtual_machine_model(self):
        """Test VirtualMachine model."""
        from app.schemas.vmware_schemas import VirtualMachine
        
        vm = VirtualMachine(
            name="test-vm",
            moid="vm-123",
            power_state="poweredOn",
            num_cpu=4,
            memory_mb=8192
        )
        
        assert vm.name == "test-vm"
        assert vm.moid == "vm-123"
        assert vm.num_cpu == 4
    
    def test_host_model(self):
        """Test Host model."""
        from app.schemas.vmware_schemas import Host
        
        host = Host(
            name="esxi01.example.com",
            moid="host-123",
            connection_state="connected",
            cpu_cores=64,
            memory_mb=524288
        )
        
        assert host.name == "esxi01.example.com"
        assert host.cpu_cores == 64
    
    def test_datastore_model(self):
        """Test Datastore model."""
        from app.schemas.vmware_schemas import Datastore
        
        ds = Datastore(
            name="DS1",
            moid="datastore-123",
            type="VMFS",
            capacity_gb=1000.0,
            free_space_gb=500.0
        )
        
        assert ds.name == "DS1"
        assert ds.capacity_gb == 1000.0
    
    def test_inventory_summary_model(self):
        """Test InventorySummary model."""
        from app.schemas.vmware_schemas import (
            InventorySummary, VCenterInfo, InventoryCounts
        )
        
        summary = InventorySummary(
            vcenter=VCenterInfo(
                name="vCenter",
                version="8.0.3",
                build="12345",
                host="vcenter.example.com"
            ),
            counts=InventoryCounts(
                datacenters=1,
                clusters=2,
                hosts=10,
                vms_total=100
            ),
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        assert summary.vcenter.version == "8.0.3"
        assert summary.counts.vms_total == 100
    
    def test_connection_test_result_model(self):
        """Test ConnectionTestResult model."""
        from app.schemas.vmware_schemas import ConnectionTestResult
        
        result = ConnectionTestResult(
            connected=True,
            host="192.168.10.5",
            vcenter_name="VMware vCenter Server",
            vcenter_version="8.0.3",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        assert result.connected is True
        assert result.vcenter_version == "8.0.3"


# =============================================================================
# CLIENT UNIT TESTS
# =============================================================================

class TestVMwareClientUnit:
    """Unit tests for VMware client."""
    
    def test_client_initialization(self, vmware_client):
        """Test client initialization."""
        assert vmware_client.host == VMWARE_HOST
        assert vmware_client.username == VMWARE_USERNAME
        assert vmware_client.port == 443
        assert vmware_client.verify_ssl is False


# =============================================================================
# INTEGRATION TESTS (LIVE VCENTER)
# =============================================================================

@pytest.mark.integration
class TestVMwareIntegration:
    """Integration tests against live vCenter."""
    
    def test_connection(self, vmware_client):
        """Test vCenter connection."""
        result = vmware_client.test_connection()
        
        assert result["connected"] is True
        assert result["vcenter_name"] is not None
        assert result["vcenter_version"] is not None
        assert "8.0" in result["vcenter_version"]
    
    def test_inventory_summary(self, vmware_client):
        """Test inventory summary retrieval."""
        summary = vmware_client.get_inventory_summary()
        
        assert "vcenter" in summary
        assert "counts" in summary
        assert summary["counts"]["datacenters"] >= 1
        assert summary["counts"]["hosts"] >= 1
    
    def test_list_datacenters(self, vmware_client):
        """Test datacenter listing."""
        datacenters = vmware_client.list_datacenters()
        
        assert isinstance(datacenters, list)
        assert len(datacenters) >= 1
        
        dc = datacenters[0]
        assert "name" in dc
        assert "moid" in dc
        assert dc["name"] == "NEXTURN-DC"
    
    def test_list_clusters(self, vmware_client):
        """Test cluster listing."""
        clusters = vmware_client.list_clusters()
        
        assert isinstance(clusters, list)
        assert len(clusters) >= 1
        
        cluster = clusters[0]
        assert "name" in cluster
        assert "datacenter" in cluster
        assert "num_hosts" in cluster
        assert cluster["name"] == "NEXTURN-CLUSTER"
    
    def test_list_hosts(self, vmware_client):
        """Test host listing."""
        hosts = vmware_client.list_hosts()
        
        assert isinstance(hosts, list)
        assert len(hosts) >= 1
        
        host = hosts[0]
        assert "name" in host
        assert "connection_state" in host
        assert "cpu_cores" in host
        assert "memory_mb" in host
        assert host["connection_state"] == "connected"
    
    def test_list_vms(self, vmware_client):
        """Test VM listing."""
        vms = vmware_client.list_vms(limit=10)
        
        assert isinstance(vms, list)
        assert len(vms) >= 1
        
        vm = vms[0]
        assert "name" in vm
        assert "moid" in vm
        assert "power_state" in vm
        assert "num_cpu" in vm
        assert "memory_mb" in vm
    
    def test_list_vms_powered_on(self, vmware_client):
        """Test VM listing filtered by power state."""
        vms = vmware_client.list_vms(power_state="poweredOn", limit=10)
        
        assert isinstance(vms, list)
        for vm in vms:
            assert vm["power_state"] == "poweredOn"
    
    def test_get_vm_by_name(self, vmware_client):
        """Test getting specific VM by name."""
        # First get a VM name from the list
        vms = vmware_client.list_vms(limit=1)
        if vms:
            vm_name = vms[0]["name"]
            
            vm = vmware_client.get_vm(name=vm_name)
            
            assert vm["name"] == vm_name
            assert "uuid" in vm
            assert "instance_uuid" in vm
    
    def test_list_datastores(self, vmware_client):
        """Test datastore listing."""
        datastores = vmware_client.list_datastores()
        
        assert isinstance(datastores, list)
        assert len(datastores) >= 1
        
        ds = datastores[0]
        assert "name" in ds
        assert "type" in ds
        assert "capacity_gb" in ds
        assert "free_space_gb" in ds
    
    def test_list_networks(self, vmware_client):
        """Test network listing."""
        networks = vmware_client.list_networks()
        
        assert isinstance(networks, list)
        assert len(networks) >= 1
        
        net = networks[0]
        assert "name" in net
        assert "type" in net
    
    def test_list_resource_pools(self, vmware_client):
        """Test resource pool listing."""
        pools = vmware_client.list_resource_pools()
        
        assert isinstance(pools, list)
        # May or may not have resource pools
        if pools:
            pool = pools[0]
            assert "name" in pool
            assert "moid" in pool


# =============================================================================
# SERVICE TESTS
# =============================================================================

@pytest.mark.integration
class TestVMwareService:
    """Tests for VMware service layer."""
    
    def test_service_connection(self, vmware_service):
        """Test service connection test."""
        result = vmware_service.test_connection()
        
        assert result.connected is True
        assert result.vcenter_name is not None
    
    def test_service_inventory_summary(self, vmware_service):
        """Test service inventory summary."""
        summary = vmware_service.get_inventory_summary()
        
        assert summary.vcenter is not None
        assert summary.counts is not None
        assert summary.counts.datacenters >= 1
    
    def test_service_list_vms(self, vmware_service):
        """Test service VM listing."""
        vms = vmware_service.list_vms(limit=5)
        
        assert isinstance(vms, list)
        assert len(vms) >= 1
    
    def test_service_search_vms(self, vmware_service):
        """Test service VM search."""
        # Search for VMs with "k8s" in name
        vms = vmware_service.search_vms(name_pattern="k8s")
        
        assert isinstance(vms, list)
        for vm in vms:
            assert "k8s" in vm["name"].lower()
    
    def test_service_get_datastore_usage(self, vmware_service):
        """Test service datastore usage summary."""
        usage = vmware_service.get_datastore_usage()
        
        assert "datastore_count" in usage
        assert "total_capacity_gb" in usage
        assert "total_free_gb" in usage
        assert "usage_percent" in usage
        assert usage["datastore_count"] >= 1
    
    def test_service_health_status(self, vmware_service):
        """Test service health status check."""
        health = vmware_service.get_health_status()
        
        assert "overall_status" in health
        assert "issues" in health
        assert "checked_at" in health
        assert health["overall_status"] in ["healthy", "warning", "critical"]
    
    def test_service_cluster_details(self, vmware_service):
        """Test service cluster details."""
        details = vmware_service.get_cluster_details("NEXTURN-CLUSTER")
        
        assert details["name"] == "NEXTURN-CLUSTER"
        assert "hosts" in details
        assert "host_count" in details
        assert details["host_count"] >= 1


# =============================================================================
# DEPENDENCY DISCOVERY TESTS
# =============================================================================

@pytest.mark.integration
class TestDependencyDiscovery:
    """Tests for dependency discovery (Agent integration)."""
    
    def test_discover_vm_dependencies(self, vmware_service):
        """Test VM dependency discovery."""
        # Get a VM name first
        vms = vmware_service.list_vms(limit=1)
        if vms:
            vm_name = vms[0]["name"]
            
            result = vmware_service.discover_vm_dependencies(vm_name)
            
            assert result.target == vm_name
            assert result.target_type == "virtual_machine"
            assert len(result.dependencies) >= 1
            
            dep = result.dependencies[0]
            assert dep.vm_name == vm_name
            assert dep.datacenter is not None
    
    def test_discover_cluster_dependencies(self, vmware_service):
        """Test cluster dependency discovery."""
        result = vmware_service.discover_cluster_dependencies("NEXTURN-CLUSTER")
        
        assert result.target == "NEXTURN-CLUSTER"
        assert result.target_type == "cluster"
        # Dependencies may be empty if no VMs in cluster (VMs are on hosts)
        assert isinstance(result.dependencies, list)


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_invalid_vm_name(self, vmware_service):
        """Test handling of invalid VM name."""
        from app.clients.vmware_client import VMwareNotFoundError
        
        with pytest.raises(VMwareNotFoundError):
            vmware_service.get_vm(name="nonexistent-vm-12345")
    
    def test_invalid_cluster_name(self, vmware_service):
        """Test handling of invalid cluster name."""
        from app.clients.vmware_client import VMwareNotFoundError
        
        with pytest.raises(VMwareNotFoundError):
            vmware_service.get_cluster_details("nonexistent-cluster")


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

if __name__ == "__main__":
    # Run all tests
    pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-m", "not integration",  # Skip integration tests by default
    ])
    
    # To run integration tests:
    # pytest test_vmware_master.py -v -m integration
