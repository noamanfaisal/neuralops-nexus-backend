import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Field = {
  name: string;
  label?: string;
  type: "text" | "number" | "select" | "checkbox";
  options?: string[];
};

type Schema = {
  title?: string;
  fields: Field[];
};

export function FormRenderer({
  metadata,
}: {
  content: string;
  metadata?: Record<string, unknown>;
}) {
  const schema = (metadata?.schema as Schema) ?? { fields: [] };
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [submitted, setSubmitted] = useState(false);

  function update(name: string, val: unknown) {
    setValues((v) => ({ ...v, [name]: val }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-md border border-border bg-card p-4"
    >
      {schema.title && (
        <div className="text-sm font-medium text-foreground">{schema.title}</div>
      )}
      {schema.fields.map((f) => (
        <div key={f.name} className="space-y-1.5">
          <Label htmlFor={f.name}>{f.label ?? f.name}</Label>
          {f.type === "select" ? (
            <Select
              onValueChange={(v) => update(f.name, v)}
              value={(values[f.name] as string) ?? ""}
            >
              <SelectTrigger id={f.name}>
                <SelectValue placeholder="Select..." />
              </SelectTrigger>
              <SelectContent>
                {f.options?.map((o) => (
                  <SelectItem key={o} value={o}>
                    {o}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : f.type === "checkbox" ? (
            <Checkbox
              id={f.name}
              checked={!!values[f.name]}
              onCheckedChange={(v) => update(f.name, !!v)}
            />
          ) : (
            <Input
              id={f.name}
              type={f.type}
              value={(values[f.name] as string) ?? ""}
              onChange={(e) => update(f.name, e.target.value)}
            />
          )}
        </div>
      ))}
      <Button type="submit" size="sm" disabled={submitted}>
        {submitted ? "Sent" : "Send Response"}
      </Button>
    </form>
  );
}
