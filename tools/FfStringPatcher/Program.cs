using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;
using Mono.Cecil;
using Mono.Cecil.Cil;

var exitCode = Run(args);
return exitCode;

static int Run(string[] args)
{
    if (args.Length == 0 || args.Any(a => a is "-h" or "--help" or "/?"))
    {
        PrintUsage();
        return args.Length == 0 ? 2 : 0;
    }

    var command = args[0].ToLowerInvariant();
    try
    {
        if (command == "export")
        {
            if (args.Length < 3)
                throw new ArgumentException("Usage: FfStringPatcher export <extracted-unityweb-dir> <translation-json> [options]");

            var root = Path.GetFullPath(args[1]);
            var outputPath = Path.GetFullPath(args[2]);
            var options = ExportOptions.Parse(args.Skip(3).ToArray());
            ExportTranslations(root, outputPath, options);
            return 0;
        }

        if (command is "apply" or "patch")
        {
            if (args.Length < 3)
                throw new ArgumentException("Usage: FfStringPatcher apply <extracted-unityweb-dir> <translation-json-or-patch-json> [options]");

            var root = Path.GetFullPath(args[1]);
            var patchPath = Path.GetFullPath(args[2]);
            var options = ApplyOptions.Parse(args.Skip(3).ToArray());
            ApplyPatchFile(root, patchPath, options);
            return 0;
        }

        // Backwards-compatible mode used by the original build script:
        // FfStringPatcher <extracted-unityweb-dir> <legacy-patch-json> [--backup]
        if (args.Length >= 2)
        {
            var root = Path.GetFullPath(args[0]);
            var patchPath = Path.GetFullPath(args[1]);
            var options = ApplyOptions.Parse(args.Skip(2).ToArray());
            ApplyPatchFile(root, patchPath, options);
            return 0;
        }

        PrintUsage();
        return 2;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.Message);
        return 1;
    }
}

static void PrintUsage()
{
    Console.Error.WriteLine(
        "Usage:\n" +
        "  FfStringPatcher export <extracted-unityweb-dir> <translation-json> [--assembly <name>] [--merge <json>]\n" +
        "  FfStringPatcher apply  <extracted-unityweb-dir> <translation-json-or-patch-json> [--backup] [--allow-missing]\n" +
        "\n" +
        "Legacy:\n" +
        "  FfStringPatcher <extracted-unityweb-dir> <legacy-patch-json> [--backup]");
}

static void ExportTranslations(string root, string outputPath, ExportOptions options)
{
    if (!Directory.Exists(root))
        throw new DirectoryNotFoundException(root);

    var assemblies = ResolveAssemblies(root, options);
    if (assemblies.Count == 0)
        throw new InvalidOperationException("No managed game assemblies were found to export.");

    var merge = TranslationMerge.Load(options.MergePaths);
    var spec = new TranslationSpec
    {
        Format = "fftools.translation.v1",
        GeneratedAt = DateTimeOffset.UtcNow.ToString("O"),
        Root = root,
        Assemblies = assemblies.Select(Path.GetFileName).Where(n => n is not null).Cast<string>().ToList(),
    };

    foreach (var assemblyPath in assemblies)
    {
        foreach (var entry in ExportAssembly(root, assemblyPath, options, merge))
            spec.Entries.Add(entry);
    }

    spec.Entries = spec.Entries
        .OrderBy(e => e.File, StringComparer.OrdinalIgnoreCase)
        .ThenBy(e => e.Type, StringComparer.Ordinal)
        .ThenBy(e => e.Method, StringComparer.Ordinal)
        .ThenBy(e => e.IlOffset)
        .ToList();

    Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
    File.WriteAllText(outputPath, ToJson(spec), Encoding.UTF8);

    var translated = spec.Entries.Count(e => !string.IsNullOrEmpty(e.Translation));
    Console.WriteLine($"Exported {spec.Entries.Count} managed ldstr entries to {outputPath}");
    Console.WriteLine($"Prefilled translations: {translated}");
}

static List<string> ResolveAssemblies(string root, ExportOptions options)
{
    if (options.AllAssemblies)
        return Directory.GetFiles(root, "*.dll").OrderBy(p => p, StringComparer.OrdinalIgnoreCase).ToList();

    var names = options.Assemblies.Count > 0
        ? options.Assemblies
        : new List<string>
        {
            "Assembly - CSharp.dll",
            "Assembly - CSharp - first pass.dll",
            "Assembly - UnityScript - first pass.dll",
        };

    return names
        .Select(name => Path.Combine(root, name))
        .Where(File.Exists)
        .OrderBy(p => p, StringComparer.OrdinalIgnoreCase)
        .ToList();
}

static IEnumerable<TranslationEntry> ExportAssembly(
    string root,
    string assemblyPath,
    ExportOptions options,
    TranslationMerge merge)
{
    var relativeFile = Path.GetRelativePath(root, assemblyPath).Replace('\\', '/');
    var resolver = BuildResolver(assemblyPath, root);
    var readerParameters = new ReaderParameters
    {
        AssemblyResolver = resolver,
        InMemory = true,
        ReadSymbols = false
    };

    using var assembly = AssemblyDefinition.ReadAssembly(assemblyPath, readerParameters);
    foreach (var module in assembly.Modules)
    {
        foreach (var type in module.Types)
        {
            foreach (var entry in ExportType(type, relativeFile, options, merge))
                yield return entry;
        }
    }
}

static IEnumerable<TranslationEntry> ExportType(
    TypeDefinition type,
    string relativeFile,
    ExportOptions options,
    TranslationMerge merge)
{
    foreach (var method in type.Methods)
    {
        if (!method.HasBody)
            continue;

        var occurrence = 0;
        foreach (var instruction in method.Body.Instructions)
        {
            if (instruction.OpCode != OpCodes.Ldstr || instruction.Operand is not string source)
                continue;

            occurrence++;
            if (!ShouldExport(source, type, method, options))
                continue;

            var entry = new TranslationEntry
            {
                Id = BuildEntryId(relativeFile, type.FullName, method.FullName, instruction.Offset, occurrence, source),
                Kind = "managed.ldstr",
                File = relativeFile,
                Type = type.FullName,
                Method = method.FullName,
                IlOffset = instruction.Offset,
                Occurrence = occurrence,
                Source = source,
                Translation = "",
            };
            entry.SourceSha1 = Sha1Hex(source);
            entry.Translation = merge.Find(entry) ?? "";
            yield return entry;
        }
    }

    foreach (var nested in type.NestedTypes)
    {
        foreach (var entry in ExportType(nested, relativeFile, options, merge))
            yield return entry;
    }
}

static bool ShouldExport(string source, TypeDefinition type, MethodDefinition method, ExportOptions options)
{
    if (source.Length < options.MinLength)
        return false;
    if (!options.IncludeEmpty && string.IsNullOrWhiteSpace(source))
        return false;
    if (source.IndexOf('\0') >= 0)
        return false;
    if (!options.IncludeControlChars && source.Any(ch => char.IsControl(ch) && ch is not '\r' and not '\n' and not '\t'))
        return false;
    if (options.UiOnly && !IsUiString(type.FullName, method.FullName, source))
        return false;
    return true;
}

static bool IsUiString(string typeName, string methodName, string source)
{
    return IsUiContext(typeName, methodName)
        && !IsTechnicalSource(source)
        && IsLikelyHumanText(source);
}

static bool IsUiContext(string typeName, string methodName)
{
    var text = (typeName + " " + methodName).ToLowerInvariant();
    var hints = new[]
    {
        "gui", "panel", "popup", "window", "login", "charselection", "charcreation",
        "namecreation", "serverselection", "missionjournal", "systemmessage",
        "optionmode", "guide", "race", "trade", "email", "vendor", "cashmall",
        "userclothes", "userstore", "quit", "worldmap", "nanocom", "menu",
        "inventory", "transport", "itemdisplay", "gum", "turing", "chat"
    };
    return hints.Any(text.Contains);
}

static bool IsTechnicalSource(string source)
{
    var text = source.Trim();
    if (text.Length == 0)
        return true;

    var lower = text.ToLowerInvariant();
    var skipValues = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "null", "none", "toggle", "label", "box", "button", "player", "transparent",
        "transparent3", "imagewindow", "left_box", "sel_box", "rightlabel",
        "closebut", "bigfont16", "jeff12skyblue", "redbutton"
    };
    if (skipValues.Contains(text))
        return true;

    if (!text.Any(char.IsLetter))
        return true;

    if (Regex.IsMatch(lower, @"^(https?://|www\.)"))
        return true;
    if (lower.Contains(".com") || lower.Contains(".php") || lower.Contains(".do"))
        return true;
    if (lower.Contains("gabage collect") || lower.Contains("garbage collect"))
        return true;
    if (text.Contains("sP_") || text.Contains("P_FE2CL") || text.Contains("P_CL2"))
        return true;
    if (Regex.IsMatch(text, @"\b(csDefines|TempItem|InventoryManagerScript|Bip01|iUiMode|slotType|iColum|PCUID)\b"))
        return true;
    if (Regex.IsMatch(lower, @"\b(click slot|inven slot|bank slot|request|receive|register form|send sell|buy ivendor|char info slot|icon is clicked)\b"))
        return true;
    if (text.Contains('/') || text.Contains('\\'))
        return true;
    if (Regex.IsMatch(lower, @"\.(png|dds|nif|mp3|wav|kfm|resourcefile|unity3d|dll|txt|xml|dat|jpg|ogg)$"))
        return true;
    if (text.Contains('_') && !text.Any(char.IsWhiteSpace))
        return true;
    if (Regex.IsMatch(text, @"\b(Get|Set|Find|Load|Init|Debug|null|curTime|sendTime|Event|mDrop|REQ|REP)\b"))
        return true;

    return false;
}

static bool IsLikelyHumanText(string source)
{
    var text = source.Trim();
    if (text.Any(char.IsWhiteSpace))
        return true;
    if (text.Any(ch => ch is '\'' or '!' or '?' or ':' or ','))
        return true;
    if (Regex.IsMatch(text, @"^[A-Z0-9][A-Z0-9 -]{1,40}$"))
        return true;
    if (Regex.IsMatch(text, @"^[A-Z][a-z]{1,24}$"))
        return true;
    if (text is "On" or "Off")
        return true;
    return false;
}

static void ApplyPatchFile(string root, string patchPath, ApplyOptions options)
{
    if (!Directory.Exists(root))
        throw new DirectoryNotFoundException(root);
    if (!File.Exists(patchPath))
        throw new FileNotFoundException("Patch JSON was not found.", patchPath);

    using var document = JsonDocument.Parse(File.ReadAllText(patchPath, Encoding.UTF8));
    if (Shared.HasProperty(document.RootElement, "entries"))
    {
        var spec = JsonSerializer.Deserialize<TranslationSpec>(
            document.RootElement.GetRawText(),
            Shared.JsonOptions()) ?? throw new InvalidOperationException("Translation JSON is empty.");
        ApplyTranslationSpec(root, spec, options);
        return;
    }

    var legacy = JsonSerializer.Deserialize<PatchSpec>(
        document.RootElement.GetRawText(),
        Shared.JsonOptions()) ?? throw new InvalidOperationException("Patch JSON is empty.");
    ApplyLegacySpec(root, legacy, options);
}

static void ApplyTranslationSpec(string root, TranslationSpec spec, ApplyOptions options)
{
    var entries = spec.Entries
        .Where(e => e.Kind is "" or "managed.ldstr")
        .Where(e => !string.IsNullOrEmpty(e.Translation))
        .ToList();

    if (entries.Count == 0)
    {
        Console.WriteLine("No filled translations to apply.");
        return;
    }

    var total = 0;
    foreach (var group in entries.GroupBy(e => NormalizeFileKey(e.File), StringComparer.OrdinalIgnoreCase))
    {
        var assemblyPath = Path.Combine(root, group.Key);
        total += PatchAssemblyByEntries(assemblyPath, root, group.ToList(), options);
    }

    Console.WriteLine($"Applied {total} translated ldstr entries.");
}

static int PatchAssemblyByEntries(
    string assemblyPath,
    string resolverRoot,
    List<TranslationEntry> entries,
    ApplyOptions options)
{
    if (!File.Exists(assemblyPath))
        throw new FileNotFoundException("Assembly was not found.", assemblyPath);

    var resolver = BuildResolver(assemblyPath, resolverRoot);
    var readerParameters = new ReaderParameters
    {
        AssemblyResolver = resolver,
        InMemory = true,
        ReadSymbols = false
    };

    using var assembly = AssemblyDefinition.ReadAssembly(assemblyPath, readerParameters);
    var pending = entries.ToDictionary(EntryApplyKey, _ => false, StringComparer.Ordinal);

    foreach (var module in assembly.Modules)
    {
        foreach (var type in module.Types)
            PatchTypeByEntries(type, entries, pending);
    }

    var patched = pending.Count(item => item.Value);
    if (patched != entries.Count && !options.AllowMissing)
    {
        var missing = pending.Where(item => !item.Value).Select(item => item.Key).Take(10);
        throw new InvalidOperationException(
            $"{Path.GetFileName(assemblyPath)}: {entries.Count - patched} translated entries were not found. First missing: {string.Join("; ", missing)}");
    }

    if (patched == 0)
        return 0;

    WriteAssembly(assembly, assemblyPath, options.Backup);
    Console.WriteLine($"{Path.GetFileName(assemblyPath)}: applied {patched} translated ldstr entries");
    return patched;
}

static void PatchTypeByEntries(
    TypeDefinition type,
    List<TranslationEntry> entries,
    Dictionary<string, bool> pending)
{
    foreach (var method in type.Methods)
    {
        if (!method.HasBody)
            continue;

        foreach (var instruction in method.Body.Instructions)
        {
            if (instruction.OpCode != OpCodes.Ldstr || instruction.Operand is not string source)
                continue;

            foreach (var entry in entries)
            {
                if (pending[EntryApplyKey(entry)])
                    continue;
                if (!SameInstruction(entry, type, method, instruction, source))
                    continue;

                instruction.Operand = entry.Translation;
                pending[EntryApplyKey(entry)] = true;
                Console.WriteLine($"{entry.File}: {entry.Source} -> {entry.Translation}");
                break;
            }
        }
    }

    foreach (var nested in type.NestedTypes)
        PatchTypeByEntries(nested, entries, pending);
}

static bool SameInstruction(
    TranslationEntry entry,
    TypeDefinition type,
    MethodDefinition method,
    Instruction instruction,
    string source)
{
    return entry.Type == type.FullName
        && entry.Method == method.FullName
        && entry.IlOffset == instruction.Offset
        && entry.Source == source;
}

static string EntryApplyKey(TranslationEntry entry)
{
    return $"{entry.File}\u001f{entry.Type}\u001f{entry.Method}\u001f{entry.IlOffset}\u001f{entry.SourceSha1}";
}

static void ApplyLegacySpec(string root, PatchSpec spec, ApplyOptions options)
{
    var total = 0;
    foreach (var file in spec.Files)
    {
        var assemblyPath = Path.Combine(root, file.Path);
        total += PatchAssemblyByLegacyReplacements(assemblyPath, root, file.Replacements, options);
    }

    Console.WriteLine($"Applied {total} legacy ldstr replacements.");
}

static int PatchAssemblyByLegacyReplacements(
    string assemblyPath,
    string resolverRoot,
    List<StringReplacement> replacements,
    ApplyOptions options)
{
    if (!File.Exists(assemblyPath))
        throw new FileNotFoundException("Assembly was not found.", assemblyPath);

    var resolver = BuildResolver(assemblyPath, resolverRoot);
    var readerParameters = new ReaderParameters
    {
        AssemblyResolver = resolver,
        InMemory = true,
        ReadSymbols = false
    };

    using var assembly = AssemblyDefinition.ReadAssembly(assemblyPath, readerParameters);
    var counts = replacements.ToDictionary(r => r.Old, _ => 0);

    foreach (var module in assembly.Modules)
    {
        foreach (var type in module.Types)
            PatchTypeByLegacyReplacements(type, replacements, counts);
    }

    foreach (var replacement in replacements)
    {
        var count = counts[replacement.Old];
        if (replacement.Count is not null && count != replacement.Count.Value)
            throw new InvalidOperationException(
                $"{Path.GetFileName(assemblyPath)}: {replacement.Old} matched {count} times, expected {replacement.Count.Value}.");
        if (count == 0 && !options.AllowMissing)
            throw new InvalidOperationException(
                $"{Path.GetFileName(assemblyPath)}: {replacement.Old} was not found.");
        if (count > 0)
            Console.WriteLine($"{Path.GetFileName(assemblyPath)}: {replacement.Old} -> {replacement.New} ({count})");
    }

    var total = counts.Values.Sum();
    if (total == 0)
        return 0;

    WriteAssembly(assembly, assemblyPath, options.Backup);
    return total;
}

static void PatchTypeByLegacyReplacements(
    TypeDefinition type,
    List<StringReplacement> replacements,
    Dictionary<string, int> counts)
{
    foreach (var method in type.Methods)
    {
        if (!method.HasBody)
            continue;

        foreach (var instruction in method.Body.Instructions)
        {
            if (instruction.OpCode != OpCodes.Ldstr || instruction.Operand is not string value)
                continue;

            foreach (var replacement in replacements)
            {
                if (value != replacement.Old)
                    continue;

                instruction.Operand = replacement.New;
                counts[replacement.Old]++;
                break;
            }
        }
    }

    foreach (var nested in type.NestedTypes)
        PatchTypeByLegacyReplacements(nested, replacements, counts);
}

static DefaultAssemblyResolver BuildResolver(string assemblyPath, string resolverRoot)
{
    var resolver = new DefaultAssemblyResolver();
    resolver.AddSearchDirectory(Path.GetDirectoryName(assemblyPath)!);
    resolver.AddSearchDirectory(resolverRoot);
    return resolver;
}

static void WriteAssembly(AssemblyDefinition assembly, string assemblyPath, bool backup)
{
    if (backup)
    {
        var backupPath = assemblyPath + ".bak";
        if (!File.Exists(backupPath))
            File.Copy(assemblyPath, backupPath);
    }

    var tempPath = assemblyPath + ".tmp";
    assembly.Write(tempPath, new WriterParameters { WriteSymbols = false });
    File.Copy(tempPath, assemblyPath, overwrite: true);
    File.Delete(tempPath);
}

static string BuildEntryId(
    string file,
    string type,
    string method,
    int ilOffset,
    int occurrence,
    string source)
{
    return $"managed.ldstr:{file}:{Sha1Hex(type + "|" + method + "|" + ilOffset + "|" + occurrence + "|" + source)[..16]}";
}

static string Sha1Hex(string value)
{
    var bytes = SHA1.HashData(Encoding.UTF8.GetBytes(value));
    return Convert.ToHexString(bytes).ToLowerInvariant();
}

static string NormalizeFileKey(string file)
{
    return file.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
}

static string ToJson<T>(T value)
{
    return JsonSerializer.Serialize(value, Shared.JsonOptions());
}

static class Shared
{
    public static JsonSerializerOptions JsonOptions()
    {
        return new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            WriteIndented = true,
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        };
    }

    public static bool HasProperty(JsonElement element, string name)
    {
        return element.ValueKind == JsonValueKind.Object
            && element.EnumerateObject().Any(property =>
                string.Equals(property.Name, name, StringComparison.OrdinalIgnoreCase));
    }

    public static string RequireValue(string[] args, ref int index, string option)
    {
        if (index + 1 >= args.Length)
            throw new ArgumentException($"{option} requires a value.");
        return args[++index];
    }
}

sealed class ExportOptions
{
    public List<string> Assemblies { get; } = new();
    public List<string> MergePaths { get; } = new();
    public int MinLength { get; private set; } = 1;
    public bool AllAssemblies { get; private set; }
    public bool IncludeEmpty { get; private set; }
    public bool IncludeControlChars { get; private set; }
    public bool UiOnly { get; private set; }

    public static ExportOptions Parse(string[] args)
    {
        var options = new ExportOptions();
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--assembly":
                case "--assemblies":
                    while (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
                        options.Assemblies.Add(args[++i]);
                    break;
                case "--all-assemblies":
                    options.AllAssemblies = true;
                    break;
                case "--ui-only":
                    options.UiOnly = true;
                    options.MinLength = Math.Max(options.MinLength, 2);
                    break;
                case "--merge":
                    options.MergePaths.Add(Path.GetFullPath(Shared.RequireValue(args, ref i, "--merge")));
                    break;
                case "--min-length":
                    options.MinLength = int.Parse(Shared.RequireValue(args, ref i, "--min-length"));
                    break;
                case "--include-empty":
                    options.IncludeEmpty = true;
                    break;
                case "--include-control-chars":
                    options.IncludeControlChars = true;
                    break;
                default:
                    throw new ArgumentException($"Unknown export option: {args[i]}");
            }
        }

        return options;
    }
}

sealed class ApplyOptions
{
    public bool Backup { get; private set; }
    public bool AllowMissing { get; private set; }

    public static ApplyOptions Parse(string[] args)
    {
        var options = new ApplyOptions();
        foreach (var arg in args)
        {
            switch (arg)
            {
                case "--backup":
                    options.Backup = true;
                    break;
                case "--allow-missing":
                    options.AllowMissing = true;
                    break;
                default:
                    throw new ArgumentException($"Unknown apply option: {arg}");
            }
        }

        return options;
    }
}

sealed class TranslationMerge
{
    private readonly Dictionary<string, string> _byId = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _byFileAndSource = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string?> _bySource = new(StringComparer.Ordinal);

    public static TranslationMerge Load(IEnumerable<string> paths)
    {
        var merge = new TranslationMerge();
        foreach (var path in paths.Where(File.Exists))
            merge.LoadPath(path);
        return merge;
    }

    public string? Find(TranslationEntry entry)
    {
        if (_byId.TryGetValue(entry.Id, out var byId))
            return byId;
        if (_byFileAndSource.TryGetValue(FileSourceKey(entry.File, entry.Source), out var byFile))
            return byFile;
        if (_bySource.TryGetValue(entry.Source, out var bySource))
            return bySource;
        return null;
    }

    private void LoadPath(string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
        if (Shared.HasProperty(document.RootElement, "entries"))
        {
            var spec = JsonSerializer.Deserialize<TranslationSpec>(document.RootElement.GetRawText(), Shared.JsonOptions());
            foreach (var entry in spec?.Entries ?? new List<TranslationEntry>())
                Add(entry.Id, entry.File, entry.Source, entry.Translation);
            return;
        }

        var legacy = JsonSerializer.Deserialize<PatchSpec>(document.RootElement.GetRawText(), Shared.JsonOptions());
        foreach (var file in legacy?.Files ?? new List<AssemblyPatch>())
        {
            foreach (var replacement in file.Replacements)
                Add(null, file.Path.Replace('\\', '/'), replacement.Old, replacement.New);
        }
    }

    private void Add(string? id, string file, string source, string? translation)
    {
        if (string.IsNullOrEmpty(translation))
            return;

        if (!string.IsNullOrEmpty(id))
            _byId[id] = translation;

        _byFileAndSource[FileSourceKey(file, source)] = translation;

        if (!_bySource.TryGetValue(source, out var existing))
        {
            _bySource[source] = translation;
        }
        else if (existing != translation)
        {
            _bySource[source] = null;
        }
    }

    private static string FileSourceKey(string file, string source)
    {
        return $"{file.Replace('\\', '/')}\u001f{source}";
    }
}

sealed class TranslationSpec
{
    public string Format { get; set; } = "fftools.translation.v1";
    public string GeneratedAt { get; set; } = "";
    public string Root { get; set; } = "";
    public List<string> Assemblies { get; set; } = new();
    public List<TranslationEntry> Entries { get; set; } = new();
}

sealed class TranslationEntry
{
    public string Id { get; set; } = "";
    public string Kind { get; set; } = "managed.ldstr";
    public string File { get; set; } = "";
    public string Type { get; set; } = "";
    public string Method { get; set; } = "";
    public int IlOffset { get; set; }
    public int Occurrence { get; set; }
    public string Source { get; set; } = "";
    public string SourceSha1 { get; set; } = "";
    public string Translation { get; set; } = "";
}

sealed class PatchSpec
{
    public List<AssemblyPatch> Files { get; set; } = new();
}

sealed class AssemblyPatch
{
    public string Path { get; set; } = "";
    public List<StringReplacement> Replacements { get; set; } = new();
}

sealed class StringReplacement
{
    public string Old { get; set; } = "";
    public string New { get; set; } = "";
    public int? Count { get; set; }
}
