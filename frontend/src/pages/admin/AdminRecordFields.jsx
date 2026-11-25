import React from 'react';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';

export const optionsFor = (rows = []) => rows.map(({ id, name }) => ({ value: id, label: name }));

export function AdminRecordFields({ fields, record = {} }) {
  return fields.map(({ name, label, options, type = 'text', optional = false, locked = false, maxLength }) => {
    const id = 'record-' + name;
    if (options) {
      return <Select key={name} id={id} name={name} label={label} options={options}
        placeholder={optional ? null : undefined} defaultValue={record[name] ?? ''} disabled={locked}
        required={!optional} />;
    }
    if (type === 'checkbox') {
      return <label key={name} className="flex items-center gap-2 self-end py-2 text-sm">
        <input name={name} type="checkbox" defaultChecked={record[name]} />{label}
      </label>;
    }
    return <Input key={name} id={id} name={name} label={label} type={type} defaultValue={record[name] ?? ''}
      required={!optional} maxLength={maxLength} min={type === 'number' ? 1 : undefined} />;
  });
}

export function recordPayload(form, fields, record) {
  const data = new FormData(form);
  return Object.fromEntries(fields.map(({ name, type, optional, locked }) => {
    const value = locked ? record[name] : data.get(name);
    if (type === 'checkbox') return [name, data.has(name)];
    if (type === 'number') return [name, Number(value)];
    return [name, optional && value === '' ? null : value];
  }));
}
