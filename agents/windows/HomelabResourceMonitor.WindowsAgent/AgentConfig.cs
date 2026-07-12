using System.Text.Json;

namespace HomelabResourceMonitor.WindowsAgent;

public sealed record AgentConfig(
    string HubUrl,
    string NodeId,
    string DisplayName,
    string Token,
    int IntervalSeconds = 2)
{
    public static AgentConfig Load(string path)
    {
        var config = JsonSerializer.Deserialize<AgentConfig>(File.ReadAllText(path), JsonOptions)
            ?? throw new InvalidDataException("empty config");
        if (!Uri.TryCreate(config.HubUrl, UriKind.Absolute, out var uri) || uri.Scheme != "http")
            throw new InvalidDataException("hub_url must be an absolute HTTP URL");
        if (string.IsNullOrWhiteSpace(config.NodeId) || string.IsNullOrWhiteSpace(config.DisplayName))
            throw new InvalidDataException("node_id and display_name are required");
        if (config.Token.Length < 32)
            throw new InvalidDataException("token must contain at least 32 characters");
        if (config.IntervalSeconds is < 1 or > 60)
            throw new InvalidDataException("interval_seconds must be 1..60");
        return config;
    }

    public static JsonSerializerOptions JsonOptions { get; } = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false
    };
}
