using System.Diagnostics;
using System.Text.Json;

return FfPatchTool.Run(args);

static class FfPatchTool
{
    private const string ConfigFileName = "ffpatch.json";
    private const string DefaultTranslationFileName = "translation.json";
    private const string DefaultManualMergeFileName = "manual.json";
    private const string DefaultAssetUrl = "http://127.0.0.1:8000";

    public static int Run(string[] args)
    {
        if (args.Length == 0 || args.Any(a => a is "-h" or "--help" or "/?"))
        {
            PrintUsage();
            return args.Length == 0 ? 2 : 0;
        }

        try
        {
            var parsed = ParsedArgs.Parse(args);
            var repoRoot = FindRepoRoot();
            return parsed.Command switch
            {
                "init" or "generate-patch" or "create-patch" => Init(repoRoot, parsed),
                "build" => Build(repoRoot, parsed),
                "make-ru" or "ru" => MakeRu(repoRoot, parsed),
                "help" => PrintAndReturnOk(),
                _ => throw new ArgumentException($"Unknown command: {parsed.Command}")
            };
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }

    private static int Init(string repoRoot, ParsedArgs args)
    {
        var source = RequireDirectory(args.Value("source"), "Specify --source <build-folder>.");
        var patchDir = ResolvePatchDir(args, source);
        Directory.CreateDirectory(patchDir);

        var translationPath = FullPath(args.Value("patch-json") ?? Path.Combine(patchDir, DefaultTranslationFileName));
        var manualMergePath = FullPath(args.Value("merge-json") ?? Path.Combine(patchDir, DefaultManualMergeFileName));
        var copiedFont = CopyFontIfRequested(args, patchDir);

        var config = LoadConfig(patchDir) ?? new PatchConfig();
        config.Source = source;
        config.TranslationJson = RelativeTo(patchDir, translationPath);
        config.ManualMergeJson = RelativeTo(patchDir, manualMergePath);
        if (copiedFont is not null)
            config.FontTtf = RelativeTo(patchDir, copiedFont);
        if (args.Value("font-face") is { Length: > 0 } fontFace)
            config.FontFace = fontFace;
        if (args.Flag("no-unity-assets"))
        {
            config.IncludeUnityAssets = false;
            config.PatchUnityAssets = false;
        }
        else if (args.Flag("include-unity-assets") || args.Flag("patch-unity-assets") || args.Flag("unity-assets"))
        {
            config.IncludeUnityAssets = true;
            config.PatchUnityAssets = true;
        }

        if (args.Flag("no-table-data"))
        {
            config.IncludeTableData = false;
            config.PatchTableData = false;
        }
        else if (args.Flag("include-table-data") || args.Flag("patch-table-data") || args.Flag("table-data"))
        {
            config.IncludeTableData = true;
            config.PatchTableData = true;
        }
        config.AssetUrl = args.Value("asset-url") ?? config.AssetUrl ?? DefaultAssetUrl;
        config.OutputName = args.Value("output-name") ?? config.OutputName ?? DefaultOutputName(source);
        SaveConfig(patchDir, config);

        Console.WriteLine($"Source:    {source}");
        Console.WriteLine($"Patch dir: {patchDir}");
        Console.WriteLine($"Patch:     {translationPath}");

        var script = Path.Combine(repoRoot, "tools", "export_translation_beta20100104.ps1");
        var psArgs = new List<string>
        {
            "-ExecutionPolicy", "Bypass",
            "-File", script,
            "-ClientDir", source,
            "-OutFile", translationPath,
            "-MergeJson", manualMergePath
        };
        if (config.IncludeUnityAssets)
            psArgs.Add("-IncludeUnityAssets");
        else
            psArgs.Add("-NoUnityAssets");
        if (config.IncludeTableData)
            psArgs.Add("-IncludeTableData");
        else
            psArgs.Add("-NoTableData");
        if (args.Flag("all-assemblies"))
            psArgs.Add("-AllAssemblies");
        if (args.Flag("all-dll-strings"))
            psArgs.Add("-AllDllStrings");

        RunProcess("powershell", psArgs, repoRoot);
        return 0;
    }

    private static int Build(string repoRoot, ParsedArgs args)
    {
        var source = ResolveSource(args);
        var patchDir = ResolvePatchDir(args, source);
        var config = LoadConfig(patchDir) ?? new PatchConfig { Source = source };
        var translationPath = ResolvePathFromPatchDir(
            patchDir,
            args.Value("patch-json") ?? config.TranslationJson ?? DefaultTranslationFileName);
        if (!File.Exists(translationPath))
            throw new FileNotFoundException($"Patch JSON was not found: {translationPath}");

        var output = ResolveOutput(args, source, config);
        var assetUrl = args.Value("asset-url") ?? config.AssetUrl ?? DefaultAssetUrl;
        var fontTtf = ResolveFontPath(args, patchDir, config);
        var fontFace = args.Value("font-face") ?? config.FontFace;

        Console.WriteLine($"Source: {source}");
        Console.WriteLine($"Patch:  {translationPath}");
        Console.WriteLine($"Output: {output}");
        if (fontTtf is not null)
            Console.WriteLine($"Font:   {fontTtf}");

        var script = Path.Combine(repoRoot, "tools", "build_ru_beta20100104.ps1");
        var psArgs = new List<string>
        {
            "-ExecutionPolicy", "Bypass",
            "-File", script,
            "-ClientDir", source,
            "-OutDir", output,
            "-PatchJson", translationPath,
            "-AssetUrl", assetUrl
        };
        if (args.Flag("force"))
            psArgs.Add("-Force");
        var patchUnityAssets = !args.Flag("no-unity-assets")
            && (args.Flag("patch-unity-assets") || args.Flag("unity-assets") || config.PatchUnityAssets);
        var patchTableData = !args.Flag("no-table-data")
            && (args.Flag("patch-table-data") || args.Flag("table-data") || config.PatchTableData);
        if (patchUnityAssets)
            psArgs.Add("-PatchUnityAssets");
        if (patchTableData)
            psArgs.Add("-PatchTableData");
        if (args.Flag("skip-manifest"))
            psArgs.Add("-SkipManifest");
        if (args.Flag("no-font-patch"))
            psArgs.Add("-NoFontPatch");
        if (args.Flag("no-font-reference-redirect"))
            psArgs.Add("-NoFontReferenceRedirect");
        if (fontTtf is not null)
        {
            psArgs.Add("-FontTtf");
            psArgs.Add(fontTtf);
        }
        if (!string.IsNullOrWhiteSpace(fontFace))
        {
            psArgs.Add("-FontFace");
            psArgs.Add(fontFace);
        }

        RunProcess("powershell", psArgs, repoRoot);
        return 0;
    }

    private static int MakeRu(string repoRoot, ParsedArgs args)
    {
        var source = RequireDirectory(args.Value("source"), "Specify --source <build-folder>.");
        var patchDir = ResolvePatchDir(args, source);
        var config = LoadConfig(patchDir);
        var translationPath = ResolvePathFromPatchDir(
            patchDir,
            args.Value("patch-json") ?? config?.TranslationJson ?? DefaultTranslationFileName);

        if (!File.Exists(translationPath) || args.Flag("regen-patch"))
        {
            Console.WriteLine("Generating patch first...");
            Init(repoRoot, args.WithCommand("init"));
        }
        else
        {
            Console.WriteLine($"Using existing patch: {translationPath}");
            if (args.Value("font-ttf") is not null || args.Value("font-face") is not null)
                UpdateFontConfig(patchDir, args);
        }

        return Build(repoRoot, args.WithCommand("build"));
    }

    private static string ResolveSource(ParsedArgs args)
    {
        if (args.Value("source") is { Length: > 0 } sourceArg)
            return RequireDirectory(sourceArg, "Source build folder was not found.");

        if (args.Value("patch-dir") is { Length: > 0 } patchArg)
        {
            var patchDir = FullPath(patchArg);
            var config = LoadConfig(patchDir);
            if (config?.Source is { Length: > 0 } sourceFromConfig)
                return RequireDirectory(sourceFromConfig, $"Configured source folder was not found: {sourceFromConfig}");
        }

        throw new ArgumentException("Specify --source <build-folder> or use --patch-dir with ffpatch.json.");
    }

    private static string ResolvePatchDir(ParsedArgs args, string source)
    {
        if (args.Value("patch-dir") is { Length: > 0 } patchDir)
            return FullPath(patchDir);

        var parent = Directory.GetParent(source)?.FullName
            ?? throw new InvalidOperationException($"Source folder has no parent: {source}");
        return Path.Combine(parent, Path.GetFileName(source.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)) + "-ru-patch");
    }

    private static string ResolveOutput(ParsedArgs args, string source, PatchConfig config)
    {
        if (args.Value("output") is { Length: > 0 } output)
            return FullPath(output);

        var explicitOutputName = args.Value("output-name");
        var outputName = explicitOutputName ?? config.OutputName ?? DefaultOutputName(source);
        if (explicitOutputName is null && string.Equals(outputName, "ru", StringComparison.OrdinalIgnoreCase))
            outputName = DefaultOutputName(source);
        if (Path.IsPathRooted(outputName))
            return FullPath(outputName);

        var parent = Directory.GetParent(source)?.FullName
            ?? throw new InvalidOperationException($"Source folder has no parent: {source}");
        return Path.Combine(parent, outputName);
    }

    private static string DefaultOutputName(string source)
    {
        return Path.GetFileName(source.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)) + "-ru";
    }

    private static string? CopyFontIfRequested(ParsedArgs args, string patchDir)
    {
        if (args.Value("font-ttf") is not { Length: > 0 } fontArg)
            return null;

        var fontPath = FullPath(fontArg);
        if (!File.Exists(fontPath))
            throw new FileNotFoundException($"TTF font was not found: {fontPath}");

        var target = Path.Combine(patchDir, "font.ttf");
        if (!PathsEqual(fontPath, target))
            File.Copy(fontPath, target, overwrite: args.Flag("force") || !File.Exists(target));
        return target;
    }

    private static void UpdateFontConfig(string patchDir, ParsedArgs args)
    {
        Directory.CreateDirectory(patchDir);
        var config = LoadConfig(patchDir) ?? new PatchConfig();
        var copiedFont = CopyFontIfRequested(args, patchDir);
        if (copiedFont is not null)
            config.FontTtf = RelativeTo(patchDir, copiedFont);
        if (args.Value("font-face") is { Length: > 0 } fontFace)
            config.FontFace = fontFace;
        SaveConfig(patchDir, config);
    }

    private static string? ResolveFontPath(ParsedArgs args, string patchDir, PatchConfig config)
    {
        if (args.Value("font-ttf") is { Length: > 0 } explicitFont)
            return RequireFile(explicitFont, "TTF font was not found.");

        if (config.FontTtf is { Length: > 0 } configuredFont)
        {
            var resolved = ResolvePathFromPatchDir(patchDir, configuredFont);
            if (File.Exists(resolved))
                return resolved;
        }

        var defaultFont = Path.Combine(patchDir, "font.ttf");
        return File.Exists(defaultFont) ? defaultFont : null;
    }

    private static string ResolvePathFromPatchDir(string patchDir, string path)
    {
        return Path.IsPathRooted(path) ? FullPath(path) : FullPath(Path.Combine(patchDir, path));
    }

    private static void RunProcess(string fileName, IReadOnlyList<string> arguments, string workingDirectory)
    {
        var start = new ProcessStartInfo(fileName)
        {
            WorkingDirectory = workingDirectory,
            UseShellExecute = false
        };
        foreach (var argument in arguments)
            start.ArgumentList.Add(argument);

        using var process = Process.Start(start)
            ?? throw new InvalidOperationException($"Could not start process: {fileName}");
        process.WaitForExit();
        if (process.ExitCode != 0)
            throw new InvalidOperationException($"{fileName} failed with exit code {process.ExitCode}");
    }

    private static PatchConfig? LoadConfig(string patchDir)
    {
        var path = Path.Combine(patchDir, ConfigFileName);
        if (!File.Exists(path))
            return null;

        return JsonSerializer.Deserialize<PatchConfig>(
            File.ReadAllText(path),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
    }

    private static void SaveConfig(string patchDir, PatchConfig config)
    {
        Directory.CreateDirectory(patchDir);
        var path = Path.Combine(patchDir, ConfigFileName);
        File.WriteAllText(
            path,
            JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true }));
    }

    private static string FindRepoRoot()
    {
        foreach (var seed in new[] { Directory.GetCurrentDirectory(), AppContext.BaseDirectory })
        {
            var current = new DirectoryInfo(seed);
            while (current is not null)
            {
                if (File.Exists(Path.Combine(current.FullName, "tools", "build_ru_beta20100104.ps1"))
                    && File.Exists(Path.Combine(current.FullName, "ffbuildtool", "Cargo.toml")))
                    return current.FullName;
                current = current.Parent;
            }
        }

        throw new DirectoryNotFoundException("Could not find FFTools repo root.");
    }

    private static string RequireDirectory(string? path, string message)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException(message);
        var full = FullPath(path);
        if (!Directory.Exists(full))
            throw new DirectoryNotFoundException($"{message} Path: {full}");
        return full;
    }

    private static string RequireFile(string path, string message)
    {
        var full = FullPath(path);
        if (!File.Exists(full))
            throw new FileNotFoundException($"{message} Path: {full}");
        return full;
    }

    private static string FullPath(string path) => Path.GetFullPath(path);

    private static string RelativeTo(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        return relative.StartsWith("..") ? path : relative;
    }

    private static bool PathsEqual(string left, string right)
    {
        return string.Equals(FullPath(left).TrimEnd('\\', '/'), FullPath(right).TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase);
    }

    private static int PrintAndReturnOk()
    {
        PrintUsage();
        return 0;
    }

    private static void PrintUsage()
    {
        Console.WriteLine(
            "Usage:\n" +
            "  FfPatchTool init    --source <build-folder> [--patch-dir <folder>] [--font-ttf <file>]\n" +
            "  FfPatchTool build   --source <build-folder> [--patch-dir <folder>] [--output-name <name>] [--force]\n" +
            "  FfPatchTool make-ru --source <build-folder> [--font-ttf <file>] [--force]\n" +
            "\n" +
            "Defaults:\n" +
            "  patch dir   = <source-folder>-ru-patch\n" +
            "  patch json  = <patch-dir>\\translation.json\n" +
            "  output      = <source-parent>\\<source-folder>-ru\n" +
            "\n" +
            "Useful flags:\n" +
            "  --unity-assets        export and patch Unity TextAsset strings too\n" +
            "  --table-data          export and patch TableData.resourceFile strings too\n" +
            "  --no-unity-assets     skip Unity TextAsset strings\n" +
            "  --no-table-data       skip TableData.resourceFile strings\n" +
            "  --font-ttf <file>     copy TTF into the patch dir and use it for GUI bitmap font glyphs\n" +
            "  <patch>\\fonts\\*.ttf  per-family fonts, e.g. fonts\\JEFFE.ttf for JEFFE___14/40/72\n" +
            "  --font-face <name>    override the Windows font face name for the TTF\n" +
            "  --regen-patch         with make-ru, export patch JSON again before building\n");
    }
}

sealed class PatchConfig
{
    public string Format { get; set; } = "fftools.patch.v1";
    public string? Source { get; set; }
    public string? TranslationJson { get; set; } = "translation.json";
    public string? ManualMergeJson { get; set; } = "manual.json";
    public string? FontTtf { get; set; }
    public string? FontFace { get; set; }
    public bool IncludeUnityAssets { get; set; } = true;
    public bool IncludeTableData { get; set; } = true;
    public bool PatchUnityAssets { get; set; } = true;
    public bool PatchTableData { get; set; } = true;
    public string AssetUrl { get; set; } = "http://127.0.0.1:8000";
    public string? OutputName { get; set; }
}

sealed class ParsedArgs
{
    private readonly Dictionary<string, string?> _options = new(StringComparer.OrdinalIgnoreCase);
    public string Command { get; private init; } = "";

    public static ParsedArgs Parse(string[] args)
    {
        var parsed = new ParsedArgs { Command = args[0].ToLowerInvariant() };
        for (var i = 1; i < args.Length; i++)
        {
            var token = args[i];
            if (!token.StartsWith("--", StringComparison.Ordinal))
                throw new ArgumentException($"Unexpected argument: {token}");

            var name = token[2..].ToLowerInvariant();
            string? value = null;
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
                value = args[++i];

            parsed._options[name] = value;
        }

        return parsed;
    }

    public string? Value(string name)
    {
        return _options.TryGetValue(name, out var value) ? value : null;
    }

    public bool Flag(string name)
    {
        return _options.ContainsKey(name) && _options[name] is null;
    }

    public ParsedArgs WithCommand(string command)
    {
        var clone = new ParsedArgs { Command = command };
        foreach (var (key, value) in _options)
            clone._options[key] = value;
        return clone;
    }
}
