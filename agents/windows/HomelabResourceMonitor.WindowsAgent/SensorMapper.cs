namespace HomelabResourceMonitor.WindowsAgent;

public static class SensorMapper
{
    public static (CpuMetrics Cpu, MemoryMetrics Memory, IReadOnlyList<GpuMetrics> Gpu) Map(
        IEnumerable<SensorReading> readings)
    {
        var sensors = readings.Where(sensor => sensor.Value is float value && float.IsFinite(value)).ToList();
        var cpu = sensors.Where(sensor => sensor.HardwareType == "Cpu").ToList();
        var memory = sensors.Where(sensor => sensor.HardwareType == "Memory").ToList();
        var gpu = sensors
            .Where(sensor => sensor.HardwareType is "GpuNvidia" or "GpuAmd" or "GpuIntel")
            .GroupBy(sensor => new { sensor.HardwareId, sensor.HardwareName })
            .Select((group, index) => new GpuMetrics(
                index.ToString(),
                group.Key.HardwareName,
                Pick(group, "Load", "GPU Core"),
                Pick(group, "Temperature", "GPU Core"),
                Pick(group, "Power", "GPU Package", "GPU Power")))
            .ToList();

        return (
            new CpuMetrics(
                Pick(cpu, "Load", "CPU Total"),
                Pick(cpu, "Temperature", "CPU Package", "Core Average"),
                Pick(cpu, "Power", "CPU Package")),
            new MemoryMetrics(Pick(memory, "Load", "Memory")),
            gpu);
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
        _ => true
    };
}
