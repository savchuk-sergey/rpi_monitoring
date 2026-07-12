using System.Diagnostics;
using System.ComponentModel;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using LibreHardwareMonitor.Hardware;

namespace HomelabResourceMonitor.WindowsAgent;

public sealed class HardwareCollector : IDisposable
{
    private readonly Computer _computer = new()
    {
        IsCpuEnabled = true,
        IsGpuEnabled = true,
        IsMemoryEnabled = true,
        IsStorageEnabled = true
    };
    private (string Id, long Received, long Sent, long Timestamp)? _previousNetwork;

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

        var (cpu, memory, gpu, storageSensors) = SensorMapper.Map(readings);
        try
        {
            var (total, available) = ReadPhysicalMemory();
            memory = ApplyPhysicalMemory(memory, total, available);
        }
        catch (Exception error)
        {
            errors.Add($"physical memory: {error.GetType().Name}");
        }
        try
        {
            gpu = MergeGpu(gpu, ParseNvidia(RunNvidiaSmi()));
        }
        catch (Exception error) when (error is TimeoutException or InvalidOperationException or FormatException)
        {
            errors.Add($"nvidia-smi: {error.GetType().Name}");
        }
        StorageMetrics storage;
        try
        {
            storage = SystemStorage(storageSensors);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            errors.Add($"storage: {error.GetType().Name}");
            storage = new(null, null, null, null, null, null, null);
        }
        NetworkMetrics network;
        try
        {
            network = Network();
        }
        catch (NetworkInformationException error)
        {
            errors.Add($"network: {error.GetType().Name}");
            network = new(null, null, null, null);
        }

        return new TelemetrySample(
            2,
            config.NodeId,
            config.DisplayName,
            DateTime.UtcNow,
            new OsMetrics("windows", Environment.OSVersion.VersionString),
            cpu,
            memory,
            gpu,
            storage,
            network,
            new HealthMetrics(Math.Max(0, Environment.TickCount64 / 1000), null, null),
            new CollectorMetrics("0.2.0", errors));
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
                if (fields.Length != 8)
                    throw new FormatException("malformed nvidia-smi output");
                var memoryUsedMib = Number(fields[4]);
                var memoryTotalMib = Number(fields[5]);
                return new GpuMetrics(
                    index.ToString(),
                    fields[0],
                    Number(fields[1]),
                    Number(fields[2]),
                    Number(fields[3]),
                    Mib(memoryUsedMib),
                    Mib(memoryTotalMib),
                    memoryUsedMib is not null && memoryTotalMib > 0
                        ? Math.Round(100 * memoryUsedMib.Value / memoryTotalMib.Value, 1)
                        : null,
                    Number(fields[6]),
                    Number(fields[7]));
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
                PowerW = gpu.PowerW ?? other.PowerW,
                MemoryUsedBytes = other.MemoryUsedBytes ?? gpu.MemoryUsedBytes,
                MemoryTotalBytes = other.MemoryTotalBytes ?? gpu.MemoryTotalBytes,
                MemoryUsagePercent = other.MemoryUsagePercent ?? gpu.MemoryUsagePercent,
                FanPercent = other.FanPercent ?? gpu.FanPercent,
                ClockMhz = other.ClockMhz ?? gpu.ClockMhz
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
                Arguments = "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total,fan.speed,clocks.gr --format=csv,noheader,nounits",
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

    private static long? Mib(double? value) =>
        value is null ? null : (long)Math.Round(value.Value * 1024 * 1024);

    public static MemoryMetrics ApplyPhysicalMemory(MemoryMetrics memory, long total, long available)
    {
        var used = Math.Max(0, total - available);
        return memory with
        {
            UsagePercent = total > 0 ? Math.Round(100d * used / total, 1) : null,
            UsedBytes = used,
            TotalBytes = total
        };
    }

    private static (long Total, long Available) ReadPhysicalMemory()
    {
        var status = new MemoryStatus { Length = (uint)Marshal.SizeOf<MemoryStatus>() };
        if (!GlobalMemoryStatusEx(ref status))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        return (checked((long)status.TotalPhysical), checked((long)status.AvailablePhysical));
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GlobalMemoryStatusEx(ref MemoryStatus status);

    [StructLayout(LayoutKind.Sequential)]
    private struct MemoryStatus
    {
        public uint Length;
        public uint MemoryLoad;
        public ulong TotalPhysical;
        public ulong AvailablePhysical;
        public ulong TotalPageFile;
        public ulong AvailablePageFile;
        public ulong TotalVirtual;
        public ulong AvailableVirtual;
        public ulong AvailableExtendedVirtual;
    }

    private static StorageMetrics SystemStorage(StorageMetrics sensors)
    {
        var drive = new DriveInfo(Path.GetPathRoot(Environment.SystemDirectory)!);
        var used = drive.TotalSize - drive.TotalFreeSpace;
        return sensors with
        {
            Name = drive.Name,
            UsagePercent = drive.TotalSize > 0 ? Math.Round(100d * used / drive.TotalSize, 1) : null,
            UsedBytes = used,
            TotalBytes = drive.TotalSize
        };
    }

    private NetworkMetrics Network()
    {
        var active = NetworkInterface.GetAllNetworkInterfaces()
            .Where(value => value.OperationalStatus == OperationalStatus.Up
                && value.NetworkInterfaceType != NetworkInterfaceType.Loopback)
            .ToList();
        var selected = active
            .Where(value => value.GetIPProperties().GatewayAddresses.Count > 0)
            .OrderByDescending(value => value.Speed)
            .FirstOrDefault()
            ?? active.OrderByDescending(value => value.Speed).FirstOrDefault();
        if (selected is null)
            return new(null, null, null, null);
        var stats = selected.GetIPv4Statistics();
        var now = Stopwatch.GetTimestamp();
        var previous = _previousNetwork;
        _previousNetwork = (selected.Id, stats.BytesReceived, stats.BytesSent, now);
        double? down = null, up = null;
        if (previous is { } value && value.Id == selected.Id && now > value.Timestamp)
        {
            var elapsed = (now - value.Timestamp) / (double)Stopwatch.Frequency;
            down = Math.Max(0, (stats.BytesReceived - value.Received) / elapsed);
            up = Math.Max(0, (stats.BytesSent - value.Sent) / elapsed);
        }
        return new(selected.Name, true, down, up);
    }
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
