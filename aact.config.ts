import type { AactConfig } from "aact";

const config: AactConfig = {
  source: {
    type: "plantuml",
    path: "./docs/architecture/c4-container.puml",
  },
  rules: {
    acl: true,
    acyclic: true,
    // Отключено осознанно: в MVP нет общего egress-шлюза, у каждой внешней системы свой ACL-адаптер.
    // Обоснование и цена — docs/adr/0003-acl-adapters-for-external-systems.md
    apiGateway: false,
    crud: true,
    dbPerService: true,
    cohesion: true,
    stableDependencies: true,
    commonReuse: true,
  },
};

export default config;
