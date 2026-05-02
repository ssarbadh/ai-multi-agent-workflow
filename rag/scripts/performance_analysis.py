#!/usr/bin/env python3
"""Performance analysis script for RAG system."""
import asyncio
import time
import statistics
import json
from typing import Dict, List, Any
from datetime import datetime, timedelta
import argparse

import httpx
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, TaskID
from rich.panel import Panel

console = Console()


class RAGPerformanceAnalyzer:
    """Analyze RAG system performance and identify bottlenecks."""
    
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def test_query_performance(self, queries: List[str], iterations: int = 5) -> Dict[str, Any]:
        """Test query performance with multiple iterations."""
        console.print(f"[bold blue]Testing query performance with {len(queries)} queries, {iterations} iterations each[/bold blue]")
        
        results = {
            "queries": [],
            "summary": {},
            "bottlenecks": []
        }
        
        with Progress() as progress:
            task = progress.add_task("Testing queries...", total=len(queries) * iterations)
            
            for query in queries:
                query_results = []
                
                for i in range(iterations):
                    start_time = time.time()
                    
                    try:
                        response = await self.client.post(
                            f"{self.base_url}/search",
                            json={"query": query, "top_k": 5}
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            duration = time.time() - start_time
                            
                            query_results.append({
                                "duration": duration,
                                "num_results": len(data.get("results", [])),
                                "success": True
                            })
                        else:
                            query_results.append({
                                "duration": time.time() - start_time,
                                "success": False,
                                "error": f"HTTP {response.status_code}"
                            })
                    
                    except Exception as e:
                        query_results.append({
                            "duration": time.time() - start_time,
                            "success": False,
                            "error": str(e)
                        })
                    
                    progress.update(task, advance=1)
                
                # Calculate statistics for this query
                successful_results = [r for r in query_results if r["success"]]
                if successful_results:
                    durations = [r["duration"] for r in successful_results]
                    
                    query_stats = {
                        "query": query[:50] + "..." if len(query) > 50 else query,
                        "success_rate": len(successful_results) / len(query_results),
                        "avg_duration": statistics.mean(durations),
                        "median_duration": statistics.median(durations),
                        "min_duration": min(durations),
                        "max_duration": max(durations),
                        "std_duration": statistics.stdev(durations) if len(durations) > 1 else 0,
                        "avg_results": statistics.mean([r["num_results"] for r in successful_results])
                    }
                    
                    results["queries"].append(query_stats)
        
        # Calculate overall summary
        if results["queries"]:
            all_durations = [q["avg_duration"] for q in results["queries"]]
            results["summary"] = {
                "total_queries": len(queries),
                "iterations_per_query": iterations,
                "overall_avg_duration": statistics.mean(all_durations),
                "overall_median_duration": statistics.median(all_durations),
                "slowest_query_duration": max(all_durations),
                "fastest_query_duration": min(all_durations),
                "avg_success_rate": statistics.mean([q["success_rate"] for q in results["queries"]])
            }
            
            # Identify bottlenecks
            results["bottlenecks"] = self._identify_bottlenecks(results["queries"])
        
        return results
    
    def _identify_bottlenecks(self, query_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify performance bottlenecks."""
        bottlenecks = []
        
        if not query_results:
            return bottlenecks
        
        durations = [q["avg_duration"] for q in query_results]
        avg_duration = statistics.mean(durations)
        
        # Identify slow queries (> 2x average)
        slow_queries = [q for q in query_results if q["avg_duration"] > avg_duration * 2]
        if slow_queries:
            bottlenecks.append({
                "type": "slow_queries",
                "description": f"{len(slow_queries)} queries are significantly slower than average",
                "threshold": avg_duration * 2,
                "affected_queries": len(slow_queries),
                "recommendation": "Investigate query complexity and optimize retrieval"
            })
        
        # Check for high variance (inconsistent performance)
        high_variance_queries = [q for q in query_results if q["std_duration"] > avg_duration * 0.5]
        if high_variance_queries:
            bottlenecks.append({
                "type": "inconsistent_performance",
                "description": f"{len(high_variance_queries)} queries have high performance variance",
                "affected_queries": len(high_variance_queries),
                "recommendation": "Check for resource contention or caching issues"
            })
        
        # Check success rate
        low_success_queries = [q for q in query_results if q["success_rate"] < 0.9]
        if low_success_queries:
            bottlenecks.append({
                "type": "low_success_rate",
                "description": f"{len(low_success_queries)} queries have success rate below 90%",
                "affected_queries": len(low_success_queries),
                "recommendation": "Investigate error causes and improve error handling"
            })
        
        return bottlenecks
    
    async def test_concurrent_performance(self, query: str, concurrent_users: int = 10, duration_seconds: int = 30) -> Dict[str, Any]:
        """Test concurrent query performance."""
        console.print(f"[bold blue]Testing concurrent performance: {concurrent_users} users for {duration_seconds}s[/bold blue]")
        
        results = {
            "concurrent_users": concurrent_users,
            "test_duration": duration_seconds,
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "avg_response_time": 0,
            "requests_per_second": 0,
            "errors": []
        }
        
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        async def worker():
            """Worker function for concurrent requests."""
            request_count = 0
            response_times = []
            errors = []
            
            while time.time() < end_time:
                try:
                    request_start = time.time()
                    response = await self.client.post(
                        f"{self.base_url}/search",
                        json={"query": query, "top_k": 5}
                    )
                    request_duration = time.time() - request_start
                    
                    request_count += 1
                    response_times.append(request_duration)
                    
                    if response.status_code != 200:
                        errors.append(f"HTTP {response.status_code}")
                
                except Exception as e:
                    request_count += 1
                    errors.append(str(e))
                
                # Small delay to prevent overwhelming the server
                await asyncio.sleep(0.1)
            
            return request_count, response_times, errors
        
        # Run concurrent workers
        tasks = [worker() for _ in range(concurrent_users)]
        worker_results = await asyncio.gather(*tasks)
        
        # Aggregate results
        total_requests = sum(r[0] for r in worker_results)
        all_response_times = []
        all_errors = []
        
        for request_count, response_times, errors in worker_results:
            all_response_times.extend(response_times)
            all_errors.extend(errors)
        
        actual_duration = time.time() - start_time
        
        results.update({
            "total_requests": total_requests,
            "successful_requests": len(all_response_times),
            "failed_requests": total_requests - len(all_response_times),
            "avg_response_time": statistics.mean(all_response_times) if all_response_times else 0,
            "requests_per_second": total_requests / actual_duration,
            "errors": list(set(all_errors))[:10]  # Unique errors, max 10
        })
        
        return results
    
    async def analyze_system_health(self) -> Dict[str, Any]:
        """Analyze overall system health."""
        console.print("[bold blue]Analyzing system health...[/bold blue]")
        
        health_data = {}
        
        try:
            # Check health endpoint
            response = await self.client.get(f"{self.base_url}/health")
            if response.status_code == 200:
                health_data["service_health"] = response.json()
            else:
                health_data["service_health"] = {"status": "unhealthy", "error": f"HTTP {response.status_code}"}
        
        except Exception as e:
            health_data["service_health"] = {"status": "unreachable", "error": str(e)}
        
        try:
            # Check evaluation status
            response = await self.client.get(f"{self.base_url}/eval/status")
            if response.status_code == 200:
                health_data["evaluation_status"] = response.json()
        
        except Exception as e:
            health_data["evaluation_status"] = {"error": str(e)}
        
        return health_data
    
    def display_results(self, performance_results: Dict[str, Any], concurrent_results: Dict[str, Any], health_data: Dict[str, Any]):
        """Display analysis results in a formatted way."""
        
        # Performance Results Table
        if performance_results.get("queries"):
            table = Table(title="Query Performance Analysis")
            table.add_column("Query", style="cyan", no_wrap=True)
            table.add_column("Success Rate", style="green")
            table.add_column("Avg Duration (s)", style="yellow")
            table.add_column("Min/Max (s)", style="blue")
            table.add_column("Std Dev", style="magenta")
            
            for query in performance_results["queries"]:
                table.add_row(
                    query["query"],
                    f"{query['success_rate']:.1%}",
                    f"{query['avg_duration']:.3f}",
                    f"{query['min_duration']:.3f}/{query['max_duration']:.3f}",
                    f"{query['std_duration']:.3f}"
                )
            
            console.print(table)
        
        # Summary Panel
        if performance_results.get("summary"):
            summary = performance_results["summary"]
            summary_text = f"""
Overall Average Duration: {summary['overall_avg_duration']:.3f}s
Overall Median Duration: {summary['overall_median_duration']:.3f}s
Fastest Query: {summary['fastest_query_duration']:.3f}s
Slowest Query: {summary['slowest_query_duration']:.3f}s
Average Success Rate: {summary['avg_success_rate']:.1%}
            """
            console.print(Panel(summary_text, title="Performance Summary", border_style="green"))
        
        # Bottlenecks
        if performance_results.get("bottlenecks"):
            console.print("\n[bold red]Identified Bottlenecks:[/bold red]")
            for bottleneck in performance_results["bottlenecks"]:
                console.print(f"• {bottleneck['description']}")
                console.print(f"  Recommendation: {bottleneck['recommendation']}")
        
        # Concurrent Performance
        if concurrent_results:
            concurrent_text = f"""
Concurrent Users: {concurrent_results['concurrent_users']}
Total Requests: {concurrent_results['total_requests']}
Successful Requests: {concurrent_results['successful_requests']}
Failed Requests: {concurrent_results['failed_requests']}
Requests per Second: {concurrent_results['requests_per_second']:.2f}
Average Response Time: {concurrent_results['avg_response_time']:.3f}s
            """
            console.print(Panel(concurrent_text, title="Concurrent Performance", border_style="blue"))
        
        # System Health
        if health_data:
            health_status = health_data.get("service_health", {}).get("status", "unknown")
            health_color = "green" if health_status == "healthy" else "red"
            console.print(f"\n[bold {health_color}]System Health: {health_status}[/bold {health_color}]")


async def main():
    """Main function to run performance analysis."""
    parser = argparse.ArgumentParser(description="RAG Performance Analysis")
    parser.add_argument("--url", default="http://localhost:8001", help="RAG service URL")
    parser.add_argument("--queries", nargs="+", default=[
        "How to troubleshoot Kubernetes pod issues?",
        "What is the incident response process?",
        "How to configure monitoring and alerting?",
        "Best practices for container security?",
        "How to handle database backup and recovery?"
    ], help="Test queries")
    parser.add_argument("--iterations", type=int, default=3, help="Iterations per query")
    parser.add_argument("--concurrent-users", type=int, default=5, help="Concurrent users for load test")
    parser.add_argument("--duration", type=int, default=30, help="Load test duration in seconds")
    parser.add_argument("--output", help="Output file for results (JSON)")
    
    args = parser.parse_args()
    
    async with RAGPerformanceAnalyzer(args.url) as analyzer:
        # Run performance tests
        performance_results = await analyzer.test_query_performance(args.queries, args.iterations)
        
        # Run concurrent performance test
        concurrent_results = await analyzer.test_concurrent_performance(
            args.queries[0], args.concurrent_users, args.duration
        )
        
        # Analyze system health
        health_data = await analyzer.analyze_system_health()
        
        # Display results
        analyzer.display_results(performance_results, concurrent_results, health_data)
        
        # Save results if output file specified
        if args.output:
            results = {
                "timestamp": datetime.now().isoformat(),
                "performance": performance_results,
                "concurrent": concurrent_results,
                "health": health_data
            }
            
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            
            console.print(f"\n[green]Results saved to {args.output}[/green]")


if __name__ == "__main__":
    asyncio.run(main())