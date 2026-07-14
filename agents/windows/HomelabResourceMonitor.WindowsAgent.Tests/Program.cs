using System.Text.Json;
using HomelabResourceMonitor.WindowsAgent;

var readings = new[]
{
    new SensorReading("cpu", "CPU", "Cpu", "Core #1", "Load", 9),
    new SensorReading("cpu", "CPU", "Cpu", "CPU Total", "Load", 34.5f),
    new SensorReading("cpu", "CPU", "Cpu", "CPU Package", "Temperature", 61),
    new SensorReading("cpu", "CPU", "Cpu", "CPU Package", "Power", 28.4f),
    new SensorReading("cpu", "CPU", "Cpu", "CPU Core #1", "Clock", 4600),
    new SensorReading("cpu", "CPU", "Cpu", "CPU Core #2", "Clock", 4800),
    new SensorReading("memory", "RAM", "Memory", "Memory", "Load", 72.1f),
    new SensorReading("memory", "RAM", "Memory", "Virtual Memory Used", "Data", 2),
    new SensorReading("memory", "RAM", "Memory", "Memory Used", "Data", 24),
    new SensorReading("memory", "RAM", "Memory", "Memory Available", "Data", 8),
    new SensorReading("memory", "RAM", "Memory", "Virtual Memory Used", "Data", 2),
    new SensorReading("memory", "RAM", "Memory", "Virtual Memory Available", "Data", 6),
    new SensorReading("gpu", "RTX", "GpuNvidia", "GPU Core", "Load", 81),
    new SensorReading("gpu", "RTX", "GpuNvidia", "GPU Core", "Temperature", 69),
    new SensorReading("gpu", "RTX", "GpuNvidia", "GPU Package", "Power", 117),
    new SensorReading("gpu", "RTX", "GpuNvidia", "GPU Memory Used", "SmallData", 6144),
    new SensorReading("gpu", "RTX", "GpuNvidia", "GPU Memory Total", "SmallData", 12288),
    new SensorReading("disk", "NVMe", "Storage", "Read Rate", "Throughput", 1250000),
    new SensorReading("disk", "NVMe", "Storage", "Write Rate", "Throughput", 640000),
    new SensorReading("disk", "NVMe", "Storage", "Temperature", "Temperature", 42),
    new SensorReading("cpu", "CPU", "Cpu", "Unsupported", "Clock", 5000),
    new SensorReading("cpu", "CPU", "Cpu", "Duplicate", "Load", 99)
};
var mapped = SensorMapper.Map(readings);
Assert(mapped.Cpu.UsagePercent == 34.5, "CPU Total mapping and duplicate handling");
Assert(mapped.Cpu.ClockMhz == 4700, "CPU clock average");
Assert(mapped.Memory.UsagePercent is > 72 and < 73, "memory mapping");
Assert(mapped.Memory.TotalBytes == 32L * 1024 * 1024 * 1024, "memory bytes");
Assert(mapped.Memory.SwapUsagePercent == 25, "virtual memory percentage");
var physicalMemory = HardwareCollector.ApplyPhysicalMemory(
    mapped.Memory, 64L * 1024 * 1024 * 1024, 36L * 1024 * 1024 * 1024);
Assert(physicalMemory.UsedBytes == 28L * 1024 * 1024 * 1024, "physical memory used");
Assert(physicalMemory.UsagePercent == 43.8, "physical memory percentage");
Assert(mapped.Gpu.Count == 1 && mapped.Gpu[0].PowerW == 117, "GPU mapping");
Assert(mapped.Gpu[0].MemoryUsagePercent == 50, "GPU memory used/total mapping");
Assert(mapped.Storage.ReadBytesPerSecond == 1250000 && mapped.Storage.TemperatureC == 42, "storage sensors");

var unsupported = SensorMapper.Map([new("cpu", "CPU", "Cpu", "Clock", "Clock", 1)]);
Assert(unsupported.Cpu.UsagePercent is null && unsupported.Gpu.Count == 0, "unsupported/null handling");
var nonFinite = SensorMapper.Map([new("cpu", "CPU", "Cpu", "CPU Total", "Load", float.NaN)]);
Assert(nonFinite.Cpu.UsagePercent is null, "NaN handling");
var zeroSensors = SensorMapper.Map([
    new("cpu", "CPU", "Cpu", "CPU Package", "Temperature", 0),
    new("cpu", "CPU", "Cpu", "CPU Package", "Power", 0)
]);
Assert(zeroSensors.Cpu.TemperatureC is null && zeroSensors.Cpu.PowerW is null, "zero unsupported sensors");

var nvidia = HardwareCollector.ParseNvidia("RTX, 81, 69, 117, 6144, 12288, 74, 2625\n");
Assert(nvidia.Count == 1 && nvidia[0].TemperatureC == 69, "nvidia-smi fixture");
Assert(nvidia[0].MemoryUsagePercent == 50 && nvidia[0].FanPercent == 74, "nvidia v2 metrics");
Assert(HardwareCollector.ParseNvidia(null).Count == 0, "missing GPU");
try { HardwareCollector.ParseNvidia("broken"); throw new Exception("malformed NVIDIA accepted"); }
catch (FormatException) { }

var capabilities = HardwareCollector.Capabilities(
    mapped.Cpu, mapped.Memory, mapped.Gpu, mapped.Storage,
    new("Ethernet", true, 1000, 500));
Assert(capabilities["cpu.power_w"].Supported, "supported capability");
Assert(capabilities["memory.pressure_some_percent"].Reason == "unsupported_os", "unsupported capability reason");

var sample = new TelemetrySample(2, "desktop", "Desktop", DateTime.UtcNow,
    new("windows", "test"), mapped.Cpu, mapped.Memory, mapped.Gpu,
    mapped.Storage, new("Ethernet", true, 1000, 500),
    new(86400, null, null), capabilities, new("0.3.0", []));
var json = JsonSerializer.Serialize(sample, AgentConfig.JsonOptions);
Assert(json.Contains("\"schema_version\":2") && !json.Contains("NaN"), "JSON serialization");
Assert(json.Contains("\"clock_mhz\":4700"), "v2 JSON fields");
Assert(json.Contains("\"capabilities\"") && json.Contains("\"unsupported_os\""), "capability JSON fields");
Assert(json.Contains("Z\""), "UTC timestamp Z serialization");
Console.WriteLine("Windows collector tests: PASS");

static void Assert(bool condition, string name)
{
    if (!condition)
        throw new Exception($"FAIL: {name}");
}
