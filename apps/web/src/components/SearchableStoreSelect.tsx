import { useEffect, useId, useMemo, useState } from "react";
import type { SelectOption } from "../types/dashboard";
import "./SearchableStoreSelect.css";

interface SearchableStoreSelectProps {
  allowEmpty?: boolean;
  emptyLabel?: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  value: string;
}

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

function optionText(option: SelectOption): string {
  return `${option.label} ${option.value}`;
}

function displayValue(options: SelectOption[], value: string): string {
  if (!value) {
    return "";
  }
  return options.find((option) => option.value === value)?.label ?? value;
}

export function SearchableStoreSelect({
  allowEmpty = false,
  emptyLabel = "全部",
  onChange,
  options,
  placeholder = "输入门店名称或 ID",
  value,
}: SearchableStoreSelectProps) {
  const inputId = useId();
  const [inputValue, setInputValue] = useState(() =>
    displayValue(options, value),
  );
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const allOptions = useMemo(() => {
    const unique = new Map<string, SelectOption>();
    if (allowEmpty) {
      unique.set("", { value: "", label: emptyLabel });
    }
    options.forEach((option) => {
      if (!unique.has(option.value)) {
        unique.set(option.value, option);
      }
    });
    return [...unique.values()];
  }, [allowEmpty, emptyLabel, options]);

  useEffect(() => {
    if (!isOpen) {
      setInputValue(displayValue(allOptions, value));
    }
  }, [allOptions, isOpen, value]);

  const filteredOptions = useMemo(() => {
    const query = normalize(inputValue);
    if (!query) {
      return allOptions.slice(0, 80);
    }
    return allOptions
      .filter((option) => normalize(optionText(option)).includes(query))
      .slice(0, 80);
  }, [allOptions, inputValue]);

  const selectOption = (option: SelectOption) => {
    onChange(option.value);
    setInputValue(option.value ? option.label : "");
    setIsOpen(false);
    setActiveIndex(0);
  };

  return (
    <div className="searchable-store-select">
      <input
        aria-autocomplete="list"
        aria-controls={`${inputId}-menu`}
        aria-expanded={isOpen}
        autoComplete="off"
        placeholder={placeholder}
        role="combobox"
        value={inputValue}
        onBlur={() => {
          window.setTimeout(() => {
            setIsOpen(false);
            setInputValue(displayValue(allOptions, value));
          }, 120);
        }}
        onChange={(event) => {
          const nextValue = event.target.value;
          setInputValue(nextValue);
          setIsOpen(true);
          setActiveIndex(0);
        }}
        onFocus={() => {
          setInputValue("");
          setIsOpen(true);
          setActiveIndex(0);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setIsOpen(true);
            setActiveIndex((current) =>
              Math.min(current + 1, Math.max(0, filteredOptions.length - 1)),
            );
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            setActiveIndex((current) => Math.max(0, current - 1));
          }
          if (event.key === "Enter" && isOpen && filteredOptions[activeIndex]) {
            event.preventDefault();
            selectOption(filteredOptions[activeIndex]);
          }
          if (event.key === "Escape") {
            setIsOpen(false);
            setInputValue(displayValue(allOptions, value));
          }
        }}
      />
      {isOpen ? (
        <div
          className="searchable-store-select__menu"
          id={`${inputId}-menu`}
          role="listbox"
        >
          {filteredOptions.length > 0 ? (
            filteredOptions.map((option, index) => (
              <div
                aria-selected={option.value === value}
                className={[
                  "searchable-store-select__option",
                  index === activeIndex ? "is-active" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                key={option.value || "__empty"}
                role="option"
                onMouseDown={(event) => {
                  event.preventDefault();
                  selectOption(option);
                }}
              >
                <strong>{option.label}</strong>
                {option.value ? <small>{option.value}</small> : null}
              </div>
            ))
          ) : (
            <div className="searchable-store-select__empty">未找到门店</div>
          )}
        </div>
      ) : null}
    </div>
  );
}
