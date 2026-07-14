namespace HomelabResourceMonitor.WindowsAgent;

public sealed record SensorReading(
    string HardwareId,
    string HardwareName,
    string HardwareType,
    string SensorName,
    string SensorType,
    float? Value);

public sealed record CpuMetrics(
    double? UsagePercent,
    double? TemperatureC,
    double? PowerW,
    double? ClockMhz);
public sealed record MemoryMetrics(
    double? UsagePercent,
    long? UsedBytes,
    long? TotalBytes,
    long? SwapUsedBytes,
    long? SwapTotalBytes,
    double? SwapUsagePercent,
    double? PressureSomePercent);
public sealed record GpuMetrics(
    string Id,
    string Name,
    double? UsagePercent,
    double? TemperatureC,
    double? PowerW,
    long? MemoryUsedBytes,
    long? MemoryTotalBytes,
    double? MemoryUsagePercent,
    double? FanPercent,
    double? ClockMhz);
public sealed record HealthMetrics(long? UptimeSeconds, bool? Undervoltage, bool? Throttled);
public sealed record StorageMetrics(
    string? Name,
    double? UsagePercent,
    long? UsedBytes,
    long? TotalBytes,
    double? ReadBytesPerSecond,
    double? WriteBytesPerSecond,
    double? TemperatureC);
public sealed record NetworkMetrics(
    string? Interface,
    bool? LinkUp,
    double? DownBytesPerSecond,
    double? UpBytesPerSecond);
public sealed record OsMetrics(string Family, string Version);
public sealed record CollectorMetrics(string Version, IReadOnlyList<string> Errors);
public sealed record MetricCapability(bool Supported, string? Source, string? Reason);

public sealed record TelemetrySample(
    int SchemaVersion,
    string NodeId,
    string DisplayName,
    DateTime TimestampUtc,
    OsMetrics Os,
    CpuMetrics Cpu,
    MemoryMetrics Memory,
    IReadOnlyList<GpuMetrics> Gpu,
    StorageMetrics Storage,
    NetworkMetrics Network,
    HealthMetrics Health,
    IReadOnlyDictionary<string, MetricCapability> Capabilities,
    CollectorMetrics Collector);
