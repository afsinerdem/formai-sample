"use client";

import { useState } from "react";

type FaqItem = {
  question: string;
  answer: string;
};

type Props = {
  items: FaqItem[];
};

export function NorthFaq({ items }: Props) {
  const [openIndex, setOpenIndex] = useState(0);

  return (
    <div className="north-faq-stack">
      {items.map((item, index) => {
        const open = index === openIndex;
        return (
          <article
            key={item.question}
            className={open ? "north-faq-card north-faq-card-open" : "north-faq-card"}
          >
            <button
              type="button"
              className="north-faq-trigger"
              aria-expanded={open}
              onClick={() => setOpenIndex((current) => (current === index ? -1 : index))}
            >
              <span>{item.question}</span>
              <span className={open ? "north-faq-icon north-faq-icon-open" : "north-faq-icon"}>+</span>
            </button>
            <div className={open ? "north-faq-answer north-faq-answer-open" : "north-faq-answer"}>
              <div className="north-faq-answer-inner">
                <p>{item.answer}</p>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
