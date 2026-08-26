import '@testing-library/jest-dom/vitest';
import {cleanup} from '@testing-library/react';
import {afterEach} from 'vitest';

// Without `globals: true`, testing-library does not auto-register cleanup, so
// renders would accumulate in document.body across tests.
afterEach(cleanup);
