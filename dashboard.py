"""Rich terminal dashboard for live metrics visualization."""

import time
import requests
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text


class StoreDashboard:
    """Live dashboard for store metrics."""
    
    def __init__(self, api_url: str = "http://localhost:8000", store_id: str = "STORE_BLR_001"):
        self.api_url = api_url
        self.store_id = store_id
        self.console = Console()
        
    def fetch_metrics(self):
        """Fetch metrics from API."""
        try:
            response = requests.get(f"{self.api_url}/stores/{self.store_id}/metrics", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def fetch_anomalies(self):
        """Fetch anomalies from API."""
        try:
            response = requests.get(f"{self.api_url}/stores/{self.store_id}/anomalies", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def create_metrics_table(self, metrics):
        """Create metrics table."""
        table = Table(title="Store Metrics", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan", width=30)
        table.add_column("Value", style="green", width=20)
        
        if "error" in metrics:
            table.add_row("Error", metrics["error"])
        else:
            table.add_row("Unique Visitors", str(metrics.get("unique_visitors", 0)))
            table.add_row("Conversion Rate", f"{metrics.get('conversion_rate', 0):.2%}")
            table.add_row("Queue Depth", str(metrics.get("queue_depth", 0)))
            table.add_row("Abandonment Rate", f"{metrics.get('abandonment_rate', 0):.2%}")
            
            # Top zone by dwell
            avg_dwell = metrics.get("avg_dwell_per_zone", {})
            if avg_dwell:
                top_zone = max(avg_dwell.items(), key=lambda x: x[1])
                table.add_row("Top Zone (Dwell)", f"{top_zone[0]} ({top_zone[1]:.0f}ms)")
        
        return table
    
    def create_zone_table(self, metrics):
        """Create zone dwell table."""
        table = Table(title="Zone Dwell Times", show_header=True, header_style="bold blue")
        table.add_column("Zone", style="cyan")
        table.add_column("Avg Dwell (ms)", style="yellow", justify="right")
        
        avg_dwell = metrics.get("avg_dwell_per_zone", {})
        
        if avg_dwell:
            for zone, dwell in sorted(avg_dwell.items(), key=lambda x: x[1], reverse=True):
                table.add_row(zone, f"{dwell:.0f}")
        else:
            table.add_row("No data", "-")
        
        return table
    
    def create_anomalies_panel(self, anomalies):
        """Create anomalies panel."""
        if "error" in anomalies:
            return Panel(f"[red]Error: {anomalies['error']}[/red]", title="Anomalies")
        
        anomaly_list = anomalies.get("anomalies", [])
        
        if not anomaly_list:
            return Panel("[green]No anomalies detected[/green]", title="Anomalies")
        
        text = Text()
        for anomaly in anomaly_list:
            severity = anomaly.get("severity", "INFO")
            color = {
                "CRITICAL": "red",
                "WARN": "yellow",
                "INFO": "blue"
            }.get(severity, "white")
            
            text.append(f"[{severity}] ", style=f"bold {color}")
            text.append(f"{anomaly.get('description', 'Unknown')}\n", style=color)
            text.append(f"  → {anomaly.get('suggested_action', 'No action')}\n\n", style="dim")
        
        return Panel(text, title="Active Anomalies", border_style="red" if any(a.get("severity") == "CRITICAL" for a in anomaly_list) else "yellow")
    
    def generate_layout(self):
        """Generate dashboard layout."""
        metrics = self.fetch_metrics()
        anomalies = self.fetch_anomalies()
        
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        
        # Header
        header_text = Text()
        header_text.append("Store Intelligence Dashboard", style="bold white on blue")
        header_text.append(f" | Store: {self.store_id} | ", style="white on blue")
        header_text.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="white on blue")
        layout["header"].update(Panel(header_text, style="blue"))
        
        # Body
        layout["body"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )
        
        layout["left"].split_column(
            Layout(self.create_metrics_table(metrics)),
            Layout(self.create_zone_table(metrics))
        )
        
        layout["right"].update(self.create_anomalies_panel(anomalies))
        
        # Footer
        footer_text = Text()
        footer_text.append("Press Ctrl+C to exit", style="dim")
        footer_text.append(" | Refreshing every 3 seconds", style="dim")
        layout["footer"].update(Panel(footer_text, style="dim"))
        
        return layout
    
    def run(self, refresh_interval: int = 3):
        """Run the live dashboard."""
        self.console.print("[bold green]Starting Store Intelligence Dashboard...[/bold green]")
        self.console.print(f"API URL: {self.api_url}")
        self.console.print(f"Store ID: {self.store_id}")
        self.console.print(f"Refresh interval: {refresh_interval} seconds\n")
        
        try:
            with Live(self.generate_layout(), refresh_per_second=1, console=self.console) as live:
                while True:
                    time.sleep(refresh_interval)
                    live.update(self.generate_layout())
        except KeyboardInterrupt:
            self.console.print("\n[bold yellow]Dashboard stopped.[/bold yellow]")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Store Intelligence Live Dashboard")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--store-id", default="STORE_BLR_001", help="Store ID to monitor")
    parser.add_argument("--refresh", type=int, default=3, help="Refresh interval in seconds")
    
    args = parser.parse_args()
    
    dashboard = StoreDashboard(api_url=args.api_url, store_id=args.store_id)
    dashboard.run(refresh_interval=args.refresh)


if __name__ == "__main__":
    main()
