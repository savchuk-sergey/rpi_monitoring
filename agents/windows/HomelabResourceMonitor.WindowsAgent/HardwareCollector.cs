using System.Diagnostics;
using System.ComponentModel;
using LibreHardwareMonitor.Hardware;

namespace HomelabResourceMonitor.WindowsAgent;

public sealed class HardwareCollector : IDisposable
{
    private readonly Computer _computer = new()
    {
        IsCpuEnabled = true,
        IsGpuEnabled = true,
        IsMemoryEnabled = true
    };

    public HardwareCollector() => _computer.Open();

    public TelemetrySample Collect(AgentConfig config)
    {
        var errors = new List<string>();
        IReadOnlyList<SensorReading> readings;
        try
        {
            _computer.Accept(new UpdateVisitor());
            readings = _computer.Hardware.SelectMany(Flatten).SelectMany(Read).ToList();
        }
        catch (Exception error)
        {
            errors.Add($"LibreHardwareMonitor: {error.GetType().Name}");
            readings = [];
        }

        var (cpu, memory, gpu) = SensorMapper.Map(readings);
        try
        {
            gpu = MergeGpu(gpu, ParseNvidia(RunNvidiaSmi()));
        }
        catch (Exception error) when (error is TimeoutException or InvalidOperationException or FormatException)
        {
            errors.Add($"nvidia-smi: {error.GetType().Name}");
        }

        return new TelemetrySample(
            1,
            config.NodeId,
            config.DisplayName,
            DateTime.UtcNow,
            new OsMetrics("windows", Environment.OSVersion.VersionString),
            cpu,
            memory,
            gpu,
            new CollectorMetrics("0.1.0", errors));
    }

    public void Dispose() => _computer.Close();

    public static IReadOnlyList<GpuMetrics> ParseNvidia(string? output)
    {
        if (string.IsNullOrWhiteSpace(output))
            return [];
        return output.Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Select((line, index) =>
            {
                var fields = line.Trim().Split(',').Select(value => value.Trim()).ToArray();
                if (fields.Length != 4)
                    throw new FormatException("malformed nvidia-smi output");
                return new GpuMetrics(
                    index.ToString(), fields[0], Number(fields[1]), Number(fields[2]), Number(fields[3]));
            })
            .ToList();
    }

    private static IEnumerable<SensorReading> Read(IHardware hardware) =>
        hardware.Sensors.Select(sensor => new SensorReading(
            hardware.Identifier.ToString(),
            hardware.Name,
            hardware.HardwareType.ToString(),
            sensor.Name,
            sensor.SensorType.ToString(),
            sensor.Value));

    private static IEnumerable<IHardware> Flatten(IHardware hardware)
    {
        yield return hardware;
        foreach (var child in hardware.SubHardware.SelectMany(Flatten))
            yield return child;
    }

    private static IReadOnlyList<GpuMetrics> MergeGpu(
        IReadOnlyList<GpuMetrics> primary,
        IReadOnlyList<GpuMetrics> fallback) =>
        primary.Count == 0 ? fallback : primary.Select((gpu, index) =>
        {
            var other = fallback.ElementAtOrDefault(index);
            return other is null ? gpu : gpu with
            {
                UsagePercent = gpu.UsagePercent ?? other.UsagePercent,
                TemperatureC = gpu.TemperatureC ?? other.TemperatureC,
                PowerW = gpu.PowerW ?? other.PowerW
            };
        }).ToList();

    private static string? RunNvidiaSmi()
    {
        Process? process;
        try
        {
            process = Process.Start(new ProcessStartInfo
            {
                FileName = "nvidia-smi.exe",
                Arguments = "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw --format=csv,noheader,nounits",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                CreateNoWindow = true
            });
        }
        catch (Win32Exception)
        {
            return null;
        }
        using (process)
        {
        if (process is null)
            return null;
        if (!process.WaitForExit(2000))
        {
            process.Kill(true);
            throw new TimeoutException();
        }
        return process.ExitCode == 0 ? process.StandardOutput.ReadToEnd() : null;
        }
    }

    private static double? Number(string value) =>
        value is "N/A" or "[Not Supported]" ? null : double.Parse(value, System.Globalization.CultureInfo.InvariantCulture);
}

internal sealed class UpdateVisitor : IVisitor
{
    public void VisitComputer(IComputer computer) => computer.Traverse(this);
    public void VisitHardware(IHardware hardware)
    {
        hardware.Update();
        foreach (var child in hardware.SubHardware)
            child.Accept(this);
    }
    public void VisitSensor(ISensor sensor) { }
    public void VisitParameter(IParameter parameter) { }
}
