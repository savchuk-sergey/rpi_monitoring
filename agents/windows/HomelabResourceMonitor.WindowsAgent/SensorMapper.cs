namespace HomelabResourceMonitor.WindowsAgent;

public static class SensorMapper
{
    public static (CpuMetrics Cpu, MemoryMetrics Memory, IReadOnlyList<GpuMetrics> Gpu, StorageMetrics Storage) Map(
        IEnumerable<SensorReading> readings)
    {
        var sensors = readings.Where(sensor => sensor.Value is float value && float.IsFinite(value)).ToList();
        var cpu = sensors.Where(sensor => sensor.HardwareType == "Cpu").ToList();
        var memory = sensors.Where(sensor => sensor.HardwareType == "Memory").ToList();
        var storage = sensors.Where(sensor => sensor.HardwareType == "Storage").ToList();
        var gpu = sensors
            .Where(sensor => sensor.HardwareType is "GpuNvidia" or "GpuAmd" or "GpuIntel")
            .GroupBy(sensor => new { sensor.HardwareId, sensor.HardwareName })
            .Select((group, index) => new GpuMetrics(
                index.ToString(),
                group.Key.HardwareName,
                Pick(group, "Load", "GPU Core"),
                Pick(group, "Temperature", "GPU Core"),
                Pick(group, "Power", "GPU Package", "GPU Power"),
                Bytes(group, "GPU Memory Used"),
                Bytes(group, "GPU Memory Total"),
                Percent(Bytes(group, "GPU Memory Used"), Bytes(group, "GPU Memory Total")),
                Pick(group, "Control", "GPU Fan"),
                Pick(group, "Clock", "GPU Core")))
            .ToList();

        var memoryUsed = Bytes(memory, "Memory Used");
        var memoryAvailable = Bytes(memory, "Memory Available");
        var swapUsed = Bytes(memory, "Virtual Memory Used");
        var swapAvailable = Bytes(memory, "Virtual Memory Available");
        var swapTotal = Sum(swapUsed, swapAvailable);

        return (
            new CpuMetrics(
                Pick(cpu, "Load", "CPU Total"),
                Pick(cpu, "Temperature", "CPU Package", "Core Average"),
                Pick(cpu, "Power", "CPU Package"),
                Average(cpu, "Clock", "Core")),
            new MemoryMetrics(
                Pick(memory, "Load", "Memory"),
                memoryUsed,
                Sum(memoryUsed, memoryAvailable),
                swapUsed,
                swapTotal,
                swapTotal > 0 && swapUsed is not null ? Math.Round(100d * swapUsed.Value / swapTotal.Value, 1) : null,
                null),
            gpu,
            new StorageMetrics(
                null, null, null, null,
                Pick(storage, "Throughput", "Read Rate", "Read"),
                Pick(storage, "Throughput", "Write Rate", "Write"),
                Pick(storage, "Temperature", "Temperature")));
    }

    private static double? Pick(
        IEnumerable<SensorReading> sensors,
        string type,
        params string[] preferredNames)
    {
        var matches = sensors.Where(sensor => sensor.SensorType == type && Valid(type, sensor.Value!.Value)).ToList();
        foreach (var name in preferredNames)
        {
            var preferred = matches.FirstOrDefault(sensor =>
                sensor.SensorName.Contains(name, StringComparison.OrdinalIgnoreCase));
            if (preferred is not null)
                return preferred.Value;
        }
        return matches.FirstOrDefault()?.Value;
    }

    private static bool Valid(string type, float value) => type switch
    {
        "Load" => value is >= 0 and <= 100,
        "Temperature" => value is > 0 and <= 150,
        "Power" => value is > 0 and <= 2000,
        "Throughput" => value >= 0,
        _ => true
    };

    private static double? Average(IEnumerable<SensorReading> sensors, string type, string name)
    {
        var values = sensors
            .Where(sensor => sensor.SensorType == type
                && sensor.SensorName.Contains(name, StringComparison.OrdinalIgnoreCase))
            .Select(sensor => (double)sensor.Value!.Value)
            .ToList();
        return values.Count == 0 ? null : Math.Round(values.Average(), 1);
    }

    private static long? Bytes(IEnumerable<SensorReading> sensors, string name)
    {
        var candidates = sensors.Where(value => value.SensorType is "Data" or "SmallData").ToList();
        var sensor = candidates.FirstOrDefault(value =>
            value.SensorName.Equals(name, StringComparison.OrdinalIgnoreCase))
            ?? candidates.FirstOrDefault(value =>
            value.SensorName.Contains(name, StringComparison.OrdinalIgnoreCase)
        );
        if (sensor?.Value is not float value)
            return null;
        var multiplier = sensor.SensorType == "Data" ? 1024d * 1024 * 1024 : 1024d * 1024;
        return (long)Math.Round(value * multiplier);
    }

    private static long? Sum(long? first, long? second) =>
        first is null || second is null ? null : first.Value + second.Value;

    private static double? Percent(long? used, long? total) =>
        used is null || total is null || total == 0 ? null : Math.Round(100d * used.Value / total.Value, 1);
}
