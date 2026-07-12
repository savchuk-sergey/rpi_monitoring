namespace HomelabResourceMonitor.WindowsAgent;

public sealed record SensorReading(
    string HardwareId,
    string HardwareName,
    string HardwareType,
    string SensorName,
    string SensorType,
    float? Value);

public sealed record CpuMetrics(double? UsagePercent, double? TemperatureC, double? PowerW);
public sealed record MemoryMetrics(double? UsagePercent);
public sealed record GpuMetrics(
    string Id,
    string Name,
    double? UsagePercent,
    double? TemperatureC,
    double? PowerW);
public sealed record OsMetrics(string Family, string Version);
public sealed record CollectorMetrics(string Version, IReadOnlyList<string> Errors);
public sealed record TelemetrySample(
    int SchemaVersion,
    string NodeId,
    string DisplayName,
    DateTime TimestampUtc,
    OsMetrics Os,
    CpuMetrics Cpu,
    MemoryMetrics Memory,
    IReadOnlyList<GpuMetrics> Gpu,
    CollectorMetrics Collector);
