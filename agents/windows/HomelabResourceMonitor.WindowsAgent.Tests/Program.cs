using System.Text.Json;
using HomelabResourceMonitor.WindowsAgent;

var readings = new[]
{
    new SensorReading("cpu", "CPU", "Cpu", "Core #1", "Load", 9),
    new SensorReading("cpu", "CPU", "Cpu", "CPU Total", "Load", 34.5f),
    new SensorReading("cpu", "CPU", "Cpu", "CPU Package", "Temperature", 61),
    new SensorReading("cpu", "CPU", "Cpu", "CPU Package", "Power", 28.4f),
    new SensorReading("memory", "RAM", "Memory", "Memory", "Load", 72.1f),
    new SensorReading("gpu", "RTX", "GpuNvidia", "GPU Core", "Load", 81),
    new SensorReading("gpu", "RTX", "GpuNvidia", "GPU Core", "Temperature", 69),
    new SensorReading("gpu", "RTX", "GpuNvidia", "GPU Package", "Power", 117),
    new SensorReading("cpu", "CPU", "Cpu", "Unsupported", "Clock", 5000),
    new SensorReading("cpu", "CPU", "Cpu", "Duplicate", "Load", 99)
};
var mapped = SensorMapper.Map(readings);
Assert(mapped.Cpu.UsagePercent == 34.5, "CPU Total mapping and duplicate handling");
Assert(mapped.Memory.UsagePercent is > 72 and < 73, "memory mapping");
Assert(mapped.Gpu.Count == 1 && mapped.Gpu[0].PowerW == 117, "GPU mapping");

var unsupported = SensorMapper.Map([new("cpu", "CPU", "Cpu", "Clock", "Clock", 1)]);
Assert(unsupported.Cpu.UsagePercent is null && unsupported.Gpu.Count == 0, "unsupported/null handling");
var nonFinite = SensorMapper.Map([new("cpu", "CPU", "Cpu", "CPU Total", "Load", float.NaN)]);
Assert(nonFinite.Cpu.UsagePercent is null, "NaN handling");
var zeroSensors = SensorMapper.Map([
    new("cpu", "CPU", "Cpu", "CPU Package", "Temperature", 0),
    new("cpu", "CPU", "Cpu", "CPU Package", "Power", 0)
]);
Assert(zeroSensors.Cpu.TemperatureC is null && zeroSensors.Cpu.PowerW is null, "zero unsupported sensors");

var nvidia = HardwareCollector.ParseNvidia("RTX, 81, 69, 117\n");
Assert(nvidia.Count == 1 && nvidia[0].TemperatureC == 69, "nvidia-smi fixture");
Assert(HardwareCollector.ParseNvidia(null).Count == 0, "missing GPU");
try { HardwareCollector.ParseNvidia("broken"); throw new Exception("malformed NVIDIA accepted"); }
catch (FormatException) { }

var sample = new TelemetrySample(1, "desktop", "Desktop", DateTime.UtcNow,
    new("windows", "test"), mapped.Cpu, mapped.Memory, mapped.Gpu, new("0.1.0", []));
var json = JsonSerializer.Serialize(sample, AgentConfig.JsonOptions);
Assert(json.Contains("\"schema_version\":1") && !json.Contains("NaN"), "JSON serialization");
Assert(json.Contains("Z\""), "UTC timestamp Z serialization");
Console.WriteLine("Windows collector tests: PASS");

static void Assert(bool condition, string name)
{
    if (!condition)
        throw new Exception($"FAIL: {name}");
}
