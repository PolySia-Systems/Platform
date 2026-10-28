import { schemas } from './contract.generated.ts';

// Interprets only the canonical Pydantic vocabulary. No code generation/eval in the browser.
type Schema = { $ref?: string; $defs?: { [key: string]: Schema }; anyOf?: readonly Schema[];
  const?: unknown; enum?: readonly unknown[]; type?: string; properties?: { [key: string]: Schema };
  required?: readonly string[]; additionalProperties?: boolean; items?: Schema; pattern?: string;
  minLength?: number; maxLength?: number; minimum?: number; maximum?: number; maxItems?: number };
function matches(value: unknown, schema: Schema, root: Schema): boolean {
  if (schema.$ref) {
    const ref = root.$defs?.[schema.$ref.split('/').at(-1) ?? ''];
    return ref !== undefined && matches(value, ref, root);
  }
  if (schema.anyOf) return schema.anyOf.some(s => matches(value, s, root));
  if ('const' in schema && value !== schema.const) return false;
  if (schema.enum && !schema.enum.includes(value)) return false;
  if (schema.type === 'null') return value === null;
  if (schema.type === 'string') return typeof value === 'string'
    && (schema.minLength === undefined || value.length >= schema.minLength)
    && (schema.maxLength === undefined || value.length <= schema.maxLength)
    && (!schema.pattern || new RegExp(schema.pattern, 'u').test(value))
    && (!schema.pattern?.startsWith('^\\d{4}-') || (!value.startsWith('0000')
      && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0,19) === value.slice(0,19)));
  if (schema.type === 'boolean') return typeof value === 'boolean';
  if (schema.type === 'integer' || schema.type === 'number') return typeof value === 'number'
    && Number.isFinite(value) && (schema.type !== 'integer' || Number.isSafeInteger(value))
    && (schema.minimum === undefined || value >= schema.minimum)
    && (schema.maximum === undefined || value <= schema.maximum);
  if (schema.type === 'array') return Array.isArray(value)
    && (schema.maxItems === undefined || value.length <= schema.maxItems)
    && schema.items !== undefined && value.every(v => matches(v, schema.items!, root));
  if (schema.type === 'object') {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
    const data = value as { [key: string]: unknown };
    const properties = schema.properties ?? {};
    return (schema.required ?? []).every(key => Object.hasOwn(data, key))
      && Object.entries(data).every(([key, v]) => Object.hasOwn(properties, key)
        ? matches(v, properties[key]!, root) : schema.additionalProperties !== false);
  }
  return 'const' in schema || schema.enum !== undefined;
}
export function validate<T>(name: keyof typeof schemas, value: unknown): T {
  const schema: Schema = schemas[name];
  if (!matches(value, schema, schema)) throw Error('incompatible_contract');
  return value as T;
}
