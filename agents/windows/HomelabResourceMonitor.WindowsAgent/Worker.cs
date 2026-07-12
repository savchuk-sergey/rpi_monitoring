using System.Net.Http.Headers;
using System.Net.Http.Json;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace HomelabResourceMonitor.WindowsAgent;

public sealed class Worker(
    AgentConfig config,
    IHttpClientFactory clients,
    HardwareCollector collector,
    ILogger<Worker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post, config.HubUrl)
                {
                    Content = JsonContent.Create(collector.Collect(config), options: AgentConfig.JsonOptions)
                };
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", config.Token);
                using var response = await clients.CreateClient("telemetry").SendAsync(request, stoppingToken);
                if (!response.IsSuccessStatusCode)
                    logger.LogWarning("Hub rejected telemetry with HTTP {StatusCode}", (int)response.StatusCode);
            }
            catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
            {
                logger.LogWarning("Hub unavailable: {ErrorType}", error.GetType().Name);
            }
            await Task.Delay(TimeSpan.FromSeconds(config.IntervalSeconds), stoppingToken);
        }
    }
}
