using HomelabResourceMonitor.WindowsAgent;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var configArgument = Array.IndexOf(args, "--config");
if (configArgument < 0 || configArgument + 1 >= args.Length)
    throw new ArgumentException("usage: --config CONFIG_FILE");

var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddWindowsService(options => options.ServiceName = "Homelab Resource Monitor Windows Agent");
builder.Services.AddSingleton(AgentConfig.Load(args[configArgument + 1]));
builder.Services.AddSingleton<HardwareCollector>();
builder.Services.AddHttpClient("telemetry", client => client.Timeout = TimeSpan.FromSeconds(5));
builder.Services.AddHostedService<Worker>();
await builder.Build().RunAsync();
