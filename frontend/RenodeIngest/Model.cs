namespace RenodeIngest;

/// <summary>
/// Intermediate records produced by the parallel per-file walk.
///
/// Cross-file references (base types, call targets) are recorded as SYMBOL KEYS
/// rather than database ids, because a file being walked cannot know the id of
/// something in a file another worker is still walking. Keys are resolved to ids
/// in a serial second pass. This is what lets pass one parallelise across all 31
/// threads while keeping output byte-identical to a single-threaded run.
/// </summary>
public sealed class FileResult
{
    public required string Path { get; init; }        // relative to the Renode tree
    public required string Sha256 { get; init; }
    public required int Loc { get; init; }
    public List<TypeRec> Types { get; } = new();
    public List<MemberRec> Members { get; } = new();
    public List<OperationRec> Operations { get; } = new();
    public List<CallSiteRec> Calls { get; } = new();
    public List<FieldAccessRec> FieldAccesses { get; } = new();

    /// Member initialisers whose operation tree was walked, and those whose
    /// declaration HAD an `= ...` clause that bound to no operation. The second
    /// number must stay 0: a non-zero value is the walker losing code, which is
    /// exactly how the first attempt at initialisers shipped zero rows while
    /// appearing to run. Reported by Ingest, never inferred from a row count.
    public int InitialisersWalked;
    public int InitialisersUnbound;
}

public sealed class TypeRec
{
    public required string Key { get; init; }          // symbol display string
    public required string Namespace { get; init; }
    public required string Name { get; init; }
    public required string Kind { get; init; }
    public string? BaseKey { get; init; }              // null when no base or base is object
    public required bool IsAbstract { get; init; }
    public required bool IsStatic { get; init; }
    public required bool IsGeneric { get; init; }
    public required string Accessibility { get; init; }
    public List<string> Interfaces { get; } = new();   // display strings
}

public sealed class MemberRec
{
    public required string Key { get; init; }
    public required string TypeKey { get; init; }
    public required string Kind { get; init; }         // field|property|method|event|ctor
    public required string Name { get; init; }
    public required string DeclaredType { get; init; }
    public required string Accessibility { get; init; }
    public required bool IsStatic { get; init; }
    public required bool IsReadOnly { get; init; }

    /// False for a computed property or a custom event -- it has no backing
    /// field, so it is not storage. See schema.sql member.has_storage.
    public bool HasStorage { get; init; } = true;

    /// Constant value for a const field or enum member; null otherwise.
    public string? ConstValue { get; init; }

    // Present only when Kind is method or ctor.
    public MethodRec? Method { get; init; }
}

public sealed class MethodRec
{
    public required string Signature { get; init; }
    public required string ReturnType { get; init; }
    public required bool IsVirtual { get; init; }
    public required bool IsAbstract { get; init; }
    public required bool IsOverride { get; init; }
    public required bool IsExtension { get; init; }
    public required bool HasBody { get; init; }
    public List<ParamRec> Parameters { get; } = new();
    public List<LocalRec> Locals { get; } = new();
}

/// <param name="DefaultValue">
/// The default's value, or null when there is none OR when the default is
/// itself null -- `HasDefault` separates those. See Walker.DefaultValueOf.
/// </param>
public sealed record ParamRec(int Ordinal, string Name, string Type,
                              bool IsOut, bool IsRef, bool IsParams, bool HasDefault,
                              string? DefaultValue);

public sealed record LocalRec(string Name, string Type, bool IsCaptured);

/// <summary>
/// One IOperation node. <see cref="LocalId"/> is unique within the file and is
/// remapped to a global id at write time; <see cref="ParentLocalId"/> refers to
/// the same local space.
/// </summary>
public sealed class OperationRec
{
    public required int LocalId { get; init; }
    public required int? ParentLocalId { get; init; }
    public required string MethodKey { get; init; }
    public required int Ordinal { get; init; }
    public required int Depth { get; init; }
    public required string Kind { get; init; }
    public string? Type { get; init; }
    public string? Symbol { get; init; }
    public string? ConstValue { get; init; }
    /// Per-kind facts as JSON; see Walker's detail switch.
    public string? Detail { get; init; }
    public required int SpanStart { get; init; }
    public required int SpanLen { get; init; }
}

public sealed record CallSiteRec(string CallerKey, string? CalleeKey, string? CalleeExtern,
                                 int OperationLocalId, bool IsVirtual);

public sealed record FieldAccessRec(string MethodKey, string MemberKey,
                                    int OperationLocalId, bool IsWrite);
