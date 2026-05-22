declare module 'dinorap-updater-ui' {
    import { DefineComponent } from 'vue';

    export const UpdaterButton: DefineComponent<{
        apiBase?: string;
    }>;
}
